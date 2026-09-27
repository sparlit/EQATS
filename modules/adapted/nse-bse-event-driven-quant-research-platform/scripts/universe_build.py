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


"""Build the research universe registry from exchange evidence.

Primary sources:
    NSE: CM UDiFF bhavcopies in raw store (all cached files, not just 5)
    BSE: bhavcopy via bseindia library (bypasses CDN block)

Every traded symbol, its series (EQ/SM/ST/... for NSE; B/A/X/MT/... for BSE)
and ISIN. This is the complete tradable universe.

Optional enrichment: MCP index/SME lists when reachable.

Output:
    data/universe/registry.json   canonical registry
    + instruments registered into the metadata store
"""


import argparse
import csv
import io
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.schemas import Exchange, InstrumentIdentity, SecurityType, Segment
from indian_quant.storage import MetadataStore

# NSE series mapping
NSE_SERIES_SEGMENT = {"EQ": "EQ", "BE": "EQ", "BZ": "EQ", "SM": "SME", "ST": "SME"}

# BSE series mapping
BSE_SERIES_SEGMENT = {
    "B": "EQ",
    "A": "EQ",
    "X": "EQ",
    "XT": "EQ",
    "G": "EQ",
    "P": "EQ",
    "IF": "EQ",
    "E": "EQ",
    "Z": "EQ",
    "R": "EQ",
    "MT": "SME",
    "M": "SME",
    "T": "SME",
    "MS": "SME",
}


def scan_nse_bhavcopies(settings) -> dict[str, dict]:
    """Scan ALL NSE bhavcopy zips in raw store (not just recent N)."""
    raw_dir = settings.data_root / "raw" / "nse" / "bhavcopy_cm_udiff"
    if not raw_dir.exists():
        return {}
    zips = sorted(raw_dir.rglob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    universe: dict[str, dict] = {}
    scanned = 0
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                reader = csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig")))
                for row in reader:
                    symbol = (row.get("TckrSymb") or "").strip().upper()
                    series = (row.get("SctySrs") or "").strip()
                    segment = NSE_SERIES_SEGMENT.get(series)
                    if not symbol or not segment:
                        continue
                    entry = universe.setdefault(
                        symbol,
                        {
                            "symbol": symbol,
                            "exchange": "NSE",
                            "segment": segment,
                            "series": series,
                            "isin": (row.get("ISIN") or "").strip() or None,
                            "source": f"bhavcopy:{zp.parent.name}",
                        },
                    )
                    # keep the freshest classification (files sorted newest first)
                    if zp == zips[0]:
                        entry["segment"] = segment
                        entry["series"] = series
        except (OSError, KeyError, zipfile.BadZipFile):
            continue
        scanned += 1
    print(f"NSE: scanned {scanned} bhavcopy files -> {len(universe)} symbols")
    return universe


def scan_bse_bhavcopies(settings) -> dict[str, dict]:
    """Scan BSE bhavcopy via bseindia library for recent trading days."""
    try:
        from bseindia import equity as bse_equity
    except ImportError:
        print("BSE: bseindia library not installed, skipping")
        return {}

    universe: dict[str, dict] = {}
    today = date.today()
    # Scan last 5 trading days to build BSE universe
    dates_to_check = []
    d = today
    attempts = 0
    while len(dates_to_check) < 5 and attempts < 14:
        if d.weekday() < 5:
            dates_to_check.append(d)
        d = d - timedelta(days=1)
        attempts += 1

    for day in dates_to_check:
        try:
            ddmmYYYY = day.strftime("%d-%m-%Y")
            df = bse_equity.equity_bhav_copy(trade_date=ddmmYYYY)
            if df is None or len(df) == 0:
                continue
            count = 0
            for _, row in df.iterrows():
                series = str(row.get("SctySrs", "")).strip()
                segment = BSE_SERIES_SEGMENT.get(series)
                if segment is None:
                    continue
                symbol = str(row.get("TckrSymb", "")).strip().upper()
                if not symbol:
                    continue
                isin = str(row.get("ISIN", "")).strip() or None
                entry = universe.setdefault(
                    symbol,
                    {
                        "symbol": symbol,
                        "exchange": "BSE",
                        "segment": segment,
                        "series": series,
                        "isin": isin,
                        "source": f"bse_bhavcopy:{day.isoformat()}",
                    },
                )
                if isin and not entry.get("isin"):
                    entry["isin"] = isin
                count += 1
            print(f"  BSE {day.isoformat()}: {count} symbols")
        except Exception as exc:
            print(f"  BSE {day.isoformat()}: skipped ({str(exc)[:60]})")

    print(f"BSE: {len(universe)} unique symbols")
    return universe


def enrich_via_mcp(settings, universe: dict[str, dict]) -> None:
    """Best-effort index/SME list enrichment; ignored when NSE blocks."""
    try:
        from indian_quant.ingestion import NseBseMcpClient

        client = NseBseMcpClient(
            settings.mcp.base_url,
            timeout=settings.mcp.timeout_seconds,
            max_retries=settings.mcp.max_retries,
        )
        for index_name, cap_bucket in (("NIFTY 500", "large+mid"), ("NIFTY SMALLCAP 250", "small")):
            try:
                entries = client.call_tool("nse_list_stocks_by_index", {"index": index_name})
                records = (
                    entries
                    if isinstance(entries, list)
                    else (entries.get("data") if isinstance(entries, dict) else []) or []
                )
                hit = 0
                for entry in records:
                    if not isinstance(entry, dict):
                        continue
                    sym = str(entry.get("symbol") or "").strip().upper()
                    if sym in universe:
                        universe[sym]["cap_bucket"] = cap_bucket
                        hit += 1
                print(f"enriched {hit} symbols <- {index_name}")
            except Exception as exc:
                print(f"{index_name} enrichment skipped ({str(exc)[:80]})")
    except Exception as exc:
        print(f"MCP enrichment unavailable ({str(exc)[:80]})")


def register_instruments(settings, universe: dict[str, dict]) -> int:
    metadata = MetadataStore(settings.storage.metadata_dsn)
    count = 0
    for item in universe.values():
        segment = Segment.SME if item["segment"] == "SME" else Segment.EQ
        exchange_val = Exchange.BSE if item["exchange"] == "BSE" else Exchange.NSE
        identity = InstrumentIdentity(
            instrument_id=f"{item['exchange']}_{segment.value}|{item['symbol']}",
            exchange=exchange_val,
            segment=segment,
            symbol=item["symbol"],
            isin=item.get("isin") or None,
            security_type=SecurityType.EQUITY,
        )
        metadata.register_instrument(
            {
                "instrument_id": identity.instrument_id,
                "exchange": identity.exchange.value,
                "segment": identity.segment.value,
                "symbol": identity.symbol,
                "isin": identity.isin,
                "security_type": identity.security_type.value,
                "lot_size": 1,
                "tick_size": 0.05,
                "nautilus_instrument_id": identity.nautilus_instrument_id,
            }
        )
        count += 1
    metadata.close()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Build universe registry")
    parser.add_argument("--no-mcp", action="store_true")
    parser.add_argument("--no-bse", action="store_true", help="Skip BSE ingestion")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)

    # Scan NSE (all cached bhavcopy files)
    universe = scan_nse_bhavcopies(settings)
    if not universe:
        print("no NSE bhavcopy raw files found - run scripts/bulk_ingest.py first")

    # Scan BSE (via bseindia library)
    if not args.no_bse:
        bse_universe = scan_bse_bhavcopies(settings)
        # Merge BSE into universe (NSE takes precedence for same symbol)
        for sym, info in bse_universe.items():
            if sym not in universe:
                universe[sym] = info
            elif universe[sym].get("exchange") == "NSE":
                # Keep NSE entry but mark as dual-listed
                universe[sym]["dual_listed"] = True
                universe[sym]["bse_isin"] = info.get("isin")

    if not universe:
        print("no data found")
        return 1

    if not args.no_mcp:
        enrich_via_mcp(settings, universe)

    counts = {
        "total": len(universe),
        "nse": sum(1 for u in universe.values() if u.get("exchange") == "NSE"),
        "bse_only": sum(1 for u in universe.values() if u.get("exchange") == "BSE"),
        "dual_listed": sum(1 for u in universe.values() if u.get("dual_listed")),
        "eq": sum(1 for u in universe.values() if u["segment"] == "EQ"),
        "sme": sum(1 for u in universe.values() if u["segment"] == "SME"),
        "with_isin": sum(1 for u in universe.values() if u.get("isin")),
    }

    out_dir = settings.data_root / "universe"
    out_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "counts": counts,
        "symbols": universe,
    }
    out_file = out_dir / "registry.json"
    out_file.write_text(json.dumps(registry, indent=2))

    registered = register_instruments(settings, universe)
    print(
        json.dumps(
            {
                "registry_file": str(out_file),
                "counts": counts,
                "instruments_registered": registered,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
