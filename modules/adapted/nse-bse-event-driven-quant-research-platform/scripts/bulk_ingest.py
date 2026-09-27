from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Bulk per-date universe ingestion: one exchange-wide download covers all symbols.

For every trading day in the window:
    1. ensure CM bhavcopy zip   (reuse cached raw zip when present)
    2. ensure delivery CSV
    3. parse BOTH into in-memory buffers, flushed once at the end:
         - bars      -> normalized/bars_1d/NSE/{SYM}.parquet   (EQ + SME segments)
         - delivery  -> normalized/delivery/NSE/{SYM}.parquet
Resumable via two layers:
    - download cache  = RawStore content-addressed payloads (idempotent)
    - parse manifest  = data/normalized/_manifests.json (dates fully parsed)

Usage:
    python scripts/bulk_ingest.py --from 2024-09-01 --to 2026-08-22 [--delivery-only]
"""


import argparse
import contextlib
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.ingestion.nse import BhavcopyIngester, parse_delivery_csv
from indian_quant.ingestion.nse.bhavcopy import SERIES_SEGMENT
from indian_quant.instruments import default_calendar
from indian_quant.quality.validators import QualityReport, detect_census_drift
from indian_quant.schemas import Timeframe
from indian_quant.storage import MetadataStore, ParquetStore, RawStore

MANIFEST_FILE = "_manifests.json"


def load_manifest(settings) -> dict[str, set[str]]:
    path = settings.normalized_dir / MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {tool: set(dates) for tool, dates in data.items()}
    except (OSError, ValueError):
        return {}


def save_manifest(settings, manifest: dict[str, set[str]]) -> None:
    settings.normalized_dir.mkdir(parents=True, exist_ok=True)
    path = settings.normalized_dir / MANIFEST_FILE
    path.write_text(json.dumps({k: sorted(v) for k, v in manifest.items()}, indent=1))


def index_raw_by_date(raw_root: Path, source: str, tool: str) -> dict[str, Path]:
    """Map request.date -> payload path from raw-store meta sidecars."""
    out: dict[str, Path] = {}
    meta_dir = raw_root / source / tool
    if not meta_dir.exists():
        return out
    ext = "zip" if "udiff" in tool else "csv"
    for meta in meta_dir.rglob("*.meta.json"):
        try:
            payload_meta = json.loads(meta.read_text())
            day = (payload_meta.get("request") or {}).get("date")
            if not day:
                continue
            payload_path = meta.with_name(meta.name.replace(".meta.json", f".{ext}"))
            if payload_path.exists():
                out.setdefault(day, payload_path)
        except (OSError, ValueError):
            continue
    return out


def census_check(
    label: str,
    raw_census: dict[str, int],
    lake_census: dict[str, int],
    bucket_map: dict[str, str] | None = None,
    ignore_buckets: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    report = QualityReport(dataset=label)
    detect_census_drift(
        raw_census, lake_census, report, label=label, bucket_map=bucket_map, ignore_buckets=ignore_buckets
    )
    return [
        i.to_dict() if hasattr(i, "to_dict") else {"severity": i.severity, "code": i.code, "detail": i.detail}
        for i in report.issues
    ]


def segment_for_series(series: str) -> str | None:
    if series in ("SM", "ST"):
        return "SME"
    if series in ("EQ", "BE", "BZ"):
        return "EQ"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk universe ingestion")
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument(
        "--exchange", default="NSE", choices=["NSE", "BSE", "both"], help="Exchange to ingest (default: NSE)"
    )
    parser.add_argument("--delivery-only", action="store_true")
    parser.add_argument("--bars-only", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--flush-every", type=int, default=60, help="persist buffers every N parsed days")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    from_d = date.fromisoformat(args.from_date)
    to_d = date.fromisoformat(args.to_date)
    calendar = default_calendar()
    store = ParquetStore(settings.data_root, settings.storage.parquet_compression)
    raw_root = settings.data_root / "raw"
    metadata = MetadataStore(settings.storage.metadata_dsn)

    do_nse = args.exchange in ("NSE", "both")
    do_bse = args.exchange in ("BSE", "both")

    manifest = load_manifest(settings)
    bars_buffer: dict[str, list[dict]] = {}
    delivery_buffer: dict[str, list[dict]] = {}
    parsed_since_flush = 0
    census_errors: list[dict] = []
    t0 = time.time()
    trading_days = calendar.trading_days_between(from_d, to_d)

    def flush_bars(exchange: str) -> int:
        written_files = 0
        for instrument_id, rows in bars_buffer.items():
            if not rows:
                continue
            if exchange not in instrument_id:
                continue
            symbol = instrument_id.split("|")[-1]
            frame = pd.DataFrame(rows)
            existing = store._path_for("normalized", "bars_1d", exchange, symbol)
            if existing.exists():
                old = pd.read_parquet(existing)
                frame = pd.concat([old, frame], ignore_index=True)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
            frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
            existing.parent.mkdir(parents=True, exist_ok=True)
            import pyarrow.parquet as pq

            pq.write_table(
                store._conform(frame),
                existing,
                compression=settings.storage.parquet_compression,
            )
            written_files += 1
        bars_buffer.clear()
        return written_files

    def flush_delivery(exchange: str) -> int:
        out_dir = settings.normalized_dir / "delivery" / exchange
        out_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for symbol, rows in delivery_buffer.items():
            target = out_dir / f"{symbol}.parquet"
            frame = pd.DataFrame(rows)
            if target.exists():
                old = pd.read_parquet(target)
                frame = pd.concat([old, frame], ignore_index=True)
            frame = frame.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            frame.to_parquet(target, index=False)
            written += 1
        delivery_buffer.clear()
        return written

    # ── NSE INGESTION ──
    if do_nse:
        print("=== NSE INGESTION ===")
        nse_ingester = BhavcopyIngester(RawStore(raw_root))
        cm_index = index_raw_by_date(raw_root, "nse", "bhavcopy_cm_udiff")
        dl_index = index_raw_by_date(raw_root, "nse", "bhavcopy_delivery_sec")

        do_bars_nse = not args.delivery_only
        do_delivery_nse = not args.bars_only

        pending_cm = [
            d for d in trading_days if do_bars_nse and d.isoformat() not in manifest.get("bars_1d_nse", set())
        ]
        pending_dl = [
            d for d in trading_days if do_delivery_nse and d.isoformat() not in manifest.get("delivery_nse", set())
        ]
        print(
            f"NSE window {from_d}..{to_d}: {len(trading_days)} trading days | "
            f"to parse: bars {len(pending_cm)}, delivery {len(pending_dl)}"
        )

        for i, day in enumerate(trading_days):
            key = day.isoformat()
            did_work = False

            if do_bars_nse and day in pending_cm:
                payload_path = cm_index.get(key)
                payload = payload_path.read_bytes() if payload_path else None
                if payload is None:
                    fetched, _ = nse_ingester.fetch_cm_zip(day)
                    payload = fetched
                    time.sleep(args.sleep)
                if payload:
                    raw_series_census: dict[str, int] = {}
                    with contextlib.suppress(Exception):
                        import csv as _csv
                        import io as _io
                        import zipfile as _zipfile

                        with _zipfile.ZipFile(_io.BytesIO(payload)) as zf:
                            cname = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                            for row in _csv.DictReader(_io.StringIO(zf.read(cname).decode("utf-8-sig"))):
                                scry = (row.get("SctySrs") or "").strip()
                                raw_series_census[scry] = raw_series_census.get(scry, 0) + 1

                    lake_segment_census: dict[str, int] = {}
                    for bar in nse_ingester.parse_cm_zip(payload, day):
                        seg_prefix = "SME" if bar.instrument_id.startswith("NSE_SME|") else "EQ"
                        lake_segment_census[seg_prefix] = lake_segment_census.get(seg_prefix, 0) + 1
                        bars_buffer.setdefault(bar.instrument_id, []).append(
                            {
                                "instrument_id": bar.instrument_id,
                                "exchange": "NSE",
                                "timestamp": bar.timestamp,
                                "timeframe": Timeframe.DAY.value,
                                "open": bar.open,
                                "high": bar.high,
                                "low": bar.low,
                                "close": bar.close,
                                "volume": bar.volume,
                                "source": "NSE",
                            }
                        )
                    ignored_series = set(raw_series_census) - set(SERIES_SEGMENT)
                    issues = census_check(
                        f"bars_nse:{key}",
                        raw_series_census,
                        lake_segment_census,
                        bucket_map={k: v.value for k, v in SERIES_SEGMENT.items()},
                        ignore_buckets=ignored_series,
                    )
                    if issues:
                        census_errors.extend(issues)
                        print(f"  CENSUS NSE bars {key}: {issues}")
                    manifest.setdefault("bars_1d_nse", set()).add(key)
                    did_work = True
                else:
                    manifest.setdefault("bars_1d_nse", set()).add(key)

            if do_delivery_nse and day in pending_dl:
                text_path = dl_index.get(key)
                text = text_path.read_text() if text_path else None
                if text is None:
                    fetched_text, _ = nse_ingester.fetch_delivery_csv(day)
                    text = fetched_text
                    time.sleep(args.sleep)
                if text:
                    raw_dl_census: dict[str, int] = {}
                    lake_dl_census: dict[str, int] = {}
                    for symbol, rec in parse_delivery_csv(text).items():
                        series = str(rec.get("series", ""))
                        raw_dl_census[series] = raw_dl_census.get(series, 0) + 1
                        segment = segment_for_series(series)
                        if segment is None or "close" not in rec:
                            continue
                        lake_dl_census[segment] = lake_dl_census.get(segment, 0) + 1
                        delivery_buffer.setdefault(symbol, []).append(
                            {
                                "date": key,
                                "symbol": symbol,
                                "segment": segment,
                                "series": series,
                                "close": float(rec["close"]),
                                "deliv_pct": (float(rec["deliv_pct"]) if rec.get("deliv_pct") is not None else None),
                                "volume": float(rec.get("volume") or 0),
                            }
                        )
                    dl_issues = census_check(
                        f"delivery_nse:{key}",
                        raw_dl_census,
                        dict(lake_dl_census.items()),
                        bucket_map={"BE": "EQ", "BZ": "EQ", "SM": "SME", "ST": "SME"},
                    )
                    if dl_issues:
                        census_errors.extend(dl_issues)
                        print(f"  CENSUS NSE delivery {key}: {dl_issues}")
                    manifest.setdefault("delivery_nse", set()).add(key)
                    did_work = True
                else:
                    manifest.setdefault("delivery_nse", set()).add(key)

            if did_work:
                parsed_since_flush += 1

            if parsed_since_flush >= args.flush_every:
                n_files_b = flush_bars("NSE")
                n_files_d = flush_delivery("NSE")
                save_manifest(settings, manifest)
                parsed_since_flush = 0
                print(
                    f"NSE [{i + 1}/{len(trading_days)}] {key} flushed "
                    f"({n_files_b} bar files, {n_files_d} delivery files, "
                    f"{time.time() - t0:.0f}s)"
                )

        n_bars_files = flush_bars("NSE") if do_bars_nse else 0
        n_deliv_files = flush_delivery("NSE") if do_delivery_nse else 0
        save_manifest(settings, manifest)
        print(f"NSE DONE in {time.time() - t0:.0f}s: wrote {n_bars_files} bar files, {n_deliv_files} delivery files")

    # ── BSE INGESTION ──
    if do_bse:
        print("=== BSE INGESTION ===")
        from indian_quant.ingestion.bse.bhavcopy import BseBhavcopyIngester

        bse_ingester = BseBhavcopyIngester()
        t0_bse = time.time()

        do_bars_bse = not args.delivery_only
        do_delivery_bse = not args.bars_only

        pending_bse = [d for d in trading_days if d.isoformat() not in manifest.get("bse_bars", set())]
        print(f"BSE window {from_d}..{to_d}: {len(pending_bse)} days to parse")

        bse_bars_buffer: dict[str, list[dict]] = {}
        bse_delivery_buffer: dict[str, list[dict]] = {}
        parsed_since_flush_bse = 0

        def flush_bse_bars() -> int:
            out_dir = settings.normalized_dir / "bars_1d" / "BSE"
            out_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            for instrument_id, rows in bse_bars_buffer.items():
                if not rows:
                    continue
                symbol = instrument_id.split("|")[-1]
                frame = pd.DataFrame(rows)
                target = out_dir / f"{symbol}.parquet"
                if target.exists():
                    old = pd.read_parquet(target)
                    frame = pd.concat([old, frame], ignore_index=True)
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
                frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
                import pyarrow.parquet as pq

                pq.write_table(
                    store._conform(frame),
                    target,
                    compression=settings.storage.parquet_compression,
                )
                written += 1
            bse_bars_buffer.clear()
            return written

        def flush_bse_delivery() -> int:
            out_dir = settings.normalized_dir / "delivery" / "BSE"
            out_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            for symbol, rows in bse_delivery_buffer.items():
                target = out_dir / f"{symbol}.parquet"
                frame = pd.DataFrame(rows)
                if target.exists():
                    old = pd.read_parquet(target)
                    frame = pd.concat([old, frame], ignore_index=True)
                frame = frame.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
                frame.to_parquet(target, index=False)
                written += 1
            bse_delivery_buffer.clear()
            return written

        for i, day in enumerate(pending_bse):
            key = day.isoformat()
            df = bse_ingester.fetch_bhavcopy(day)
            time.sleep(args.sleep)

            if df is not None and len(df) > 0:
                if do_bars_bse:
                    for bar in bse_ingester.parse_bhavcopy(df, day):
                        bse_bars_buffer.setdefault(bar.instrument_id, []).append(
                            {
                                "instrument_id": bar.instrument_id,
                                "exchange": "BSE",
                                "timestamp": bar.timestamp,
                                "timeframe": Timeframe.DAY.value,
                                "open": bar.open,
                                "high": bar.high,
                                "low": bar.low,
                                "close": bar.close,
                                "volume": bar.volume,
                                "source": "BSE",
                            }
                        )

                if do_delivery_bse:
                    for symbol, rec in bse_ingester.parse_bhavcopy_to_delivery(df, day).items():
                        bse_delivery_buffer.setdefault(symbol, []).append(
                            {
                                "date": key,
                                "symbol": symbol,
                                "segment": rec.get("segment", "EQ"),
                                "series": rec.get("series", "B"),
                                "close": float(rec["close"]),
                                "deliv_pct": rec.get("deliv_pct"),
                                "volume": float(rec.get("volume") or 0),
                            }
                        )

                manifest.setdefault("bse_bars", set()).add(key)
                manifest.setdefault("bse_delivery", set()).add(key)
            else:
                manifest.setdefault("bse_bars", set()).add(key)
                manifest.setdefault("bse_delivery", set()).add(key)

            parsed_since_flush_bse += 1
            if parsed_since_flush_bse >= args.flush_every:
                n_b = flush_bse_bars()
                n_d = flush_bse_delivery()
                save_manifest(settings, manifest)
                parsed_since_flush_bse = 0
                print(
                    f"BSE [{i + 1}/{len(pending_bse)}] {key} flushed "
                    f"({n_b} bar files, {n_d} delivery files, "
                    f"{time.time() - t0_bse:.0f}s)"
                )

        n_bars_bse = flush_bse_bars() if do_bars_bse else 0
        n_deliv_bse = flush_bse_delivery() if do_delivery_bse else 0
        save_manifest(settings, manifest)
        print(f"BSE DONE in {time.time() - t0_bse:.0f}s: wrote {n_bars_bse} bar files, {n_deliv_bse} delivery files")

    # ── METADATA ──
    sources = []
    if do_nse:
        sources.append("NSE")
    if do_bse:
        sources.append("BSE")
    job_id = f"bulk-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    metadata.start_job(
        job_id,
        tool="bulk_ingest",
        source="+".join(sources),
        params={"from": args.from_date, "to": args.to_date, "exchange": args.exchange},
    )
    metadata.finish_job(job_id, status="OK", rows=0)
    metadata.close()

    if census_errors:
        print(f"CENSUS ERRORS: {len(census_errors)}")
        for e in census_errors[:10]:
            print(" ", e)
        return 2
    print("census parity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
