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


#!/usr/bin/env python3
"""Ingest fundamental data for all stocks into PostgreSQL.

Data sources (cascade): FinStack key_ratios → Indian Market MCP → yfinance
Stores: company_profile, key_ratios

Usage:
    python scripts/ingest_fundamentals.py                    # Full universe
    python scripts/ingest_fundamentals.py --recent           # Only recently traded
    python scripts/ingest_fundamentals.py --symbol RELIANCE  # Single stock
    python scripts/ingest_fundamentals.py --batch-size 50 --sleep 2
"""


import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.pipeline.fundamentals import (
    ingest_all_fundamentals,
    ingest_fundamentals,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_fundamentals")


def main():
    parser = argparse.ArgumentParser(description="Ingest fundamental data into PostgreSQL")
    parser.add_argument("--symbol", help="Single symbol to ingest")
    parser.add_argument("--symbols", nargs="+", help="List of symbols to ingest")
    parser.add_argument("--recent", action="store_true", help="Only recently traded stocks")
    parser.add_argument("--batch-size", type=int, default=50, help="Symbols per batch")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args()

    if args.symbol:
        ok = ingest_fundamentals(args.symbol.upper())
        print(f"{'OK' if ok else 'NO DATA'}: {args.symbol}")
    elif args.symbols:
        for sym in args.symbols:
            ok = ingest_fundamentals(sym.upper())
            print(f"{'OK' if ok else 'NO DATA'}: {sym}")
    else:
        result = ingest_all_fundamentals(
            recent=args.recent,
            batch_size=args.batch_size,
            sleep=args.sleep,
        )
        print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
