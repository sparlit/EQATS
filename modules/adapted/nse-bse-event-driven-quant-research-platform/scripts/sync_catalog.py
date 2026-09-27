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


"""Sync validated bars into the Nautilus ParquetDataCatalog.

Usage:
    python scripts/sync_catalog.py --symbol RELIANCE
"""


import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.nautilus.data.catalog import sync_validated_to_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync validated data to Nautilus catalog")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    written = sync_validated_to_catalog(
        validated_dir=settings.validated_dir,
        catalog_path=settings.catalog_dir,
        exchange=args.exchange,
        symbols=[args.symbol.upper()] if args.symbol else None,
        timeframe=args.timeframe,
    )
    if not written:
        print("nothing synced; run scripts/validate.py first")
        return 1
    for inst_id, bt in written.items():
        print(f"{inst_id} -> {bt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
