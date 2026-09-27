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


"""Per-symbol NSE announcements backfill for the liquid research subset.

Ranks symbols by median delivery-lake turnover (close x volume), then
pulls announcements in monthly chunks via MCP (per-symbol responses are
small enough to avoid the response limiter's size cap).

Resumable: data/normalized/_ann_manifest.json tracks (symbol -> [YYYY-MM]).

Usage:
    python scripts/announcements_backfill.py --top 150 --years 2
"""


import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.ingestion import NseBseMcpClient, NseIngestionService
from indian_quant.storage import MetadataStore, RawStore

ANN_MANIFEST = "_ann_manifest.json"


def liquidity_ranking(settings, top_n: int) -> list[tuple[str, float]]:
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    scores: list[tuple[str, float]] = []
    for path in dl_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(path, columns=["symbol", "segment", "close", "volume"])
        except Exception:
            continue
        if df.empty or df["segment"].iloc[0] != "EQ":
            continue
        notional = (df["close"] * df["volume"]).dropna()
        if len(notional) < 100:
            continue
        scores.append((str(df["symbol"].iloc[0]), float(notional.median())))
    scores.sort(key=lambda t: -t[1])
    return scores[:top_n]


def month_chunks(from_d: date, to_d: date) -> list[tuple[date, date]]:
    """First-to-last-day chunks aligned to calendar months."""
    from datetime import timedelta

    chunks: list[tuple[date, date]] = []
    cur = from_d
    while cur <= to_d:
        first_next = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
        end = min(first_next - timedelta(days=1), to_d)
        chunks.append((cur, end))
        cur = end + timedelta(days=1)
    return chunks


def load_manifest(settings) -> dict[str, list[str]]:
    path = settings.normalized_dir / ANN_MANIFEST
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(settings, manifest: dict[str, list[str]]) -> None:
    settings.normalized_dir.mkdir(parents=True, exist_ok=True)
    (settings.normalized_dir / ANN_MANIFEST).write_text(json.dumps(manifest, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Liquid-subset announcements backfill")
    parser.add_argument("--top", type=int, default=150)
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    from_d = date.fromisoformat(args.from_date)
    to_d = date.fromisoformat(args.to_date)
    chunks = month_chunks(from_d, to_d)

    ranked = liquidity_ranking(settings, args.top)
    print(f"liquidity-ranked symbols: {len(ranked)} (median notional top: {ranked[0][0]} ₹{ranked[0][1]:,.0f})")

    client = NseBseMcpClient(
        settings.mcp.base_url,
        timeout=settings.mcp.timeout_seconds * 4,
        max_retries=settings.mcp.max_retries,
    )
    raw = RawStore(settings.data_root / "raw")
    metadata = MetadataStore(settings.storage.metadata_dsn)
    service = NseIngestionService(client, raw, metadata)

    out_dir = settings.normalized_dir / "announcements" / "NSE"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(settings)

    total_ann = 0
    t0 = time.time()
    for si, (symbol, _notional) in enumerate(ranked):
        done_months = set(manifest.get(symbol, []))
        all_rows: list[dict] = []
        for frm, to in chunks:
            tag = f"{frm.year}-{frm.month:02d}"
            if tag in done_months:
                continue
            try:
                anns = service.corporate_announcements(symbol, frm, to)
            except Exception as exc:
                print(f"  {symbol} {tag}: FAILED {str(exc)[:70]}")
                time.sleep(args.sleep)
                continue
            for a in anns:
                all_rows.append(
                    {
                        "announcement_id": a.announcement_id,
                        "published_at": a.published_at,
                        "category": a.category,
                        "headline": a.headline[:200],
                        "document_url": a.document_url,
                    }
                )
            done_months.add(tag)
            manifest.setdefault(symbol, []).append(tag)
            time.sleep(args.sleep)
        if all_rows:
            frame = pd.DataFrame(all_rows).drop_duplicates(subset=["announcement_id"])
            target = out_dir / f"{symbol}.parquet"
            if target.exists():
                old = pd.read_parquet(target)
                frame = (
                    pd.concat([old, frame], ignore_index=True)
                    .drop_duplicates(subset=["announcement_id"])
                    .sort_values("published_at")
                )
            frame.to_parquet(target, index=False)
            total_ann += len(frame)
        save_manifest(settings, manifest)
        if (si + 1) % 10 == 0:
            print(
                f"[{si + 1}/{len(ranked)}] {symbol}: cumulative announcements {total_ann:,} ({time.time() - t0:.0f}s)"
            )

    print(f"DONE in {time.time() - t0:.0f}s: {total_ann:,} announcements across {len(ranked)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
