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
"""
Backfill missing option premium data for specific dates.
─────────────────────────────────────────────────────────
Fetches 1-min option bars from TrueData for dates that have
NIFTY-I index candles but no option premium data.

Usage:
  python scripts/backfill_option_days.py                  # auto-detect missing days
  python scripts/backfill_option_days.py 2026-03-19 2026-03-20 2026-03-23  # specific days
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from backtest.option_resolver import build_option_symbol, get_nearest_expiry
from data.truedata_adapter import TrueDataAdapter
from utils.logger import get_logger

from database.db import read_sql, upsert_candles

logger = get_logger("backfill_options")

# ATM ± N strikes to fetch (7 strikes = ATM ±3 × CE+PE = 14 symbols)
N_STRIKES = 3
STRIKE_GAP = 50


def find_missing_option_days() -> list:
    """Find all trading days that have NIFTY-I candles but no option data."""
    candle_days = read_sql(
        "SELECT DISTINCT timestamp::date as day FROM minute_candles WHERE symbol = 'NIFTY-I' ORDER BY 1"
    )
    option_days = read_sql(
        "SELECT DISTINCT timestamp::date as day FROM minute_candles "
        "WHERE symbol LIKE 'NIFTY%%CE' OR symbol LIKE 'NIFTY%%PE' ORDER BY 1"
    )
    candle_set = {str(d) for d in candle_days["day"]}
    option_set = {str(d) for d in option_days["day"]}
    return sorted(candle_set - option_set)


def get_nifty_close_for_date(dt_str: str) -> float:
    """Get the NIFTY-I closing price for a given date (for ATM calculation)."""
    df = read_sql(
        "SELECT close FROM minute_candles WHERE symbol = 'NIFTY-I' "
        "AND timestamp::date = :dt ORDER BY timestamp DESC LIMIT 1",
        {"dt": dt_str},
    )
    if df.empty:
        return 0.0
    return float(df.iloc[0]["close"])


def backfill_day(td: TrueDataAdapter, day_str: str):
    """Fetch and store option premium bars for a single day."""
    day = datetime.strptime(day_str, "%Y-%m-%d").date()
    nifty_close = get_nifty_close_for_date(day_str)
    if nifty_close == 0:
        print(f"  ✗ {day_str}: No NIFTY-I candle data, skipping")
        return 0

    atm = round(nifty_close / STRIKE_GAP) * STRIKE_GAP
    expiry = get_nearest_expiry(day)
    if expiry is None:
        print(f"  ✗ {day_str}: No expiry found, skipping")
        return 0

    print(f"  {day_str}: NIFTY={nifty_close:.0f}  ATM={atm}  Expiry={expiry}")

    # Market hours for the day
    market_open = datetime(day.year, day.month, day.day, 9, 15, 0)
    market_close = datetime(day.year, day.month, day.day, 15, 30, 0)

    total_bars = 0
    symbols_fetched = 0

    for offset in range(-N_STRIKES, N_STRIKES + 1):
        strike = atm + offset * STRIKE_GAP
        for opt_type in ["CE", "PE"]:
            sym = build_option_symbol(expiry, strike, opt_type)

            # Check if we already have data for this symbol+day
            existing = read_sql(
                "SELECT COUNT(*) as cnt FROM minute_candles WHERE symbol = :sym AND timestamp::date = :dt",
                {"sym": sym, "dt": day_str},
            )
            if not existing.empty and existing.iloc[0]["cnt"] > 0:
                continue  # already have data

            try:
                bars = td.fetch_historical_bars(sym, market_open, market_close, "1min")
                if bars.empty:
                    continue

                bars = bars.copy()
                bars["symbol"] = sym
                # Ensure required columns
                for col in ["vwap", "oi"]:
                    if col not in bars.columns:
                        bars[col] = 0
                cols = ["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap", "oi"]
                bars = bars[[c for c in cols if c in bars.columns]]

                upsert_candles(bars)
                total_bars += len(bars)
                symbols_fetched += 1
                print(f"    {sym}: {len(bars)} bars")
            except Exception as e:
                print(f"    {sym}: ERROR {e}")

    print(f"  → {day_str}: {symbols_fetched} symbols, {total_bars} bars upserted")
    return total_bars


def main():
    # Determine which days to backfill
    days = sys.argv[1:] if len(sys.argv) > 1 else find_missing_option_days()

    if not days:
        print("No missing option days found. All good!")
        return

    print(f"Days to backfill option premiums: {len(days)}")
    for d in days:
        print(f"  {d}")

    # Authenticate with TrueData
    td = TrueDataAdapter()
    if not td.authenticate():
        print("ERROR: TrueData authentication failed.")
        return

    print(f"\nFetching ATM±{N_STRIKES} strikes (CE+PE) = {(2 * N_STRIKES + 1) * 2} symbols per day\n")

    grand_total = 0
    for day_str in days:
        bars = backfill_day(td, day_str)
        grand_total += bars

    print(f"\n{'=' * 50}")
    print(f"BACKFILL COMPLETE: {grand_total} total bars across {len(days)} days")

    # Verify
    print("\nVerification:")
    for day_str in days:
        count = read_sql(
            "SELECT COUNT(DISTINCT symbol) as syms, COUNT(*) as bars "
            "FROM minute_candles WHERE timestamp::date = :dt "
            "AND (symbol LIKE 'NIFTY%%CE' OR symbol LIKE 'NIFTY%%PE')",
            {"dt": day_str},
        )
        if not count.empty:
            r = count.iloc[0]
            status = "✓" if r["syms"] > 0 else "✗"
            print(f"  {status} {day_str}: {r['syms']} symbols, {r['bars']} bars")


if __name__ == "__main__":
    main()
