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
Backfill today's missing 1-min candles from TrueData REST API.
Run this once to fill any gap caused by a late start or collector downtime.
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from data.truedata_adapter import TrueDataAdapter
from utils.logger import get_logger

from database.db import read_sql, upsert_candles

logger = get_logger("backfill")


def backfill_today():
    today = date.today()
    today_str = today.isoformat()
    print(f"Backfilling candles for {today_str}...")

    td = TrueDataAdapter()
    if not td.authenticate():
        print("ERROR: TrueData authentication failed.")
        return

    # Fetch all available symbols that should have data today
    # First figure out what we already have
    existing = read_sql(
        "SELECT MIN(timestamp) as first, MAX(timestamp) as last, COUNT(*) as bars "
        "FROM minute_candles WHERE symbol='NIFTY-I' AND timestamp::date = :dt",
        {"dt": today_str},
    )
    if not existing.empty and existing.iloc[0]["bars"] > 0:
        last_ts = existing.iloc[0]["last"]
        print(f"  Existing NIFTY-I candles: {int(existing.iloc[0]['bars'])} bars, last at {last_ts}")
    else:
        print("  No existing candles for today.")

    # Fetch full day bars using start=9:15, end=now
    market_open = datetime(today.year, today.month, today.day, 9, 15, 0)
    now = datetime.now()
    print(f"  Fetching NIFTY-I 1-min bars from {market_open.strftime('%H:%M')} to {now.strftime('%H:%M')}...")
    bars = td.fetch_historical_bars("NIFTY-I", start=market_open, end=now, interval="1min")
    if bars.empty:
        print("  ERROR: No bars returned from TrueData.")
        return

    today_bars = bars.copy()
    today_bars["symbol"] = "NIFTY-I"

    print(f"  Got {len(today_bars)} bars. Upserting to DB...")
    upsert_candles(today_bars)
    print(f"  Done. Upserted {len(today_bars)} NIFTY-I bars.")

    # Also fetch option candles for ATM strikes
    if not today_bars.empty:
        current_price = float(today_bars.iloc[-1]["close"])
        atm = round(current_price / 50) * 50
        print(f"  Current NIFTY: {current_price:.1f}, ATM: {atm}")

        from datetime import timedelta

        from backtest.option_resolver import build_option_symbol, get_nearest_expiry

        expiry = get_nearest_expiry(today)
        # If nearest expiry is in the past (expired contract), fall forward to next Tuesday
        if expiry and expiry < today:
            days_ahead = 1 - today.weekday()  # Tuesday = 1
            if days_ahead <= 0:
                days_ahead += 7
            expiry = today + timedelta(days=days_ahead)
            print(f"  Expiry was expired ({expiry - timedelta(days=days_ahead)}), using next Tuesday: {expiry}")
        if expiry:
            print(f"  Nearest expiry: {expiry}")
            symbols = []
            for offset in [0, 50, -50, 100, -100, 150, -150]:
                strike = atm + offset
                symbols.append(build_option_symbol(expiry, strike, "CE"))
                symbols.append(build_option_symbol(expiry, strike, "PE"))

            fetched = 0
            for sym in symbols:
                try:
                    opt_bars = td.fetch_historical_bars(sym, start=market_open, end=now, interval="1min")
                    if opt_bars.empty:
                        continue
                    opt_bars = opt_bars.copy()
                    opt_bars["symbol"] = sym
                    upsert_candles(opt_bars)
                    fetched += len(opt_bars)
                    print(f"    {sym}: {len(opt_bars)} bars")
                except Exception as e:
                    print(f"    {sym}: ERROR {e}")
            print(f"  Option candles upserted: {fetched} total bars")

    # Final count
    final = read_sql(
        "SELECT COUNT(*) as bars, MIN(timestamp) as first, MAX(timestamp) as last "
        "FROM minute_candles WHERE symbol='NIFTY-I' AND timestamp::date = :dt",
        {"dt": today_str},
    )
    if not final.empty:
        r = final.iloc[0]
        print(f"\n  NIFTY-I candles for {today_str}: {int(r['bars'])} bars ({r['first']} → {r['last']})")


if __name__ == "__main__":
    backfill_today()
