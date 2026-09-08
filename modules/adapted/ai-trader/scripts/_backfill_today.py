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
"""One-shot: backfill today's missing NIFTY-I candles and ATM option candles from 9:15 to now."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from datetime import date, datetime

import pandas as pd
from backtest.option_resolver import get_nearest_expiry
from data.truedata_adapter import TrueDataAdapter

from database.db import read_sql, upsert_candles

today = date.today()
day_start = datetime(today.year, today.month, today.day, 9, 15, 0)
end_dt = datetime.now()

print(f"Backfilling today ({today}) from 09:15 to {end_dt.strftime('%H:%M')}...")

td = TrueDataAdapter()
if not td.authenticate():
    print("ERROR: TrueData auth failed")
    sys.exit(1)
print("Auth OK")

# 1. NIFTY-I candles
bars = td.fetch_historical_bars("NIFTY-I", day_start, end_dt, interval="1min")
if bars.empty:
    print("WARNING: No NIFTY-I bars returned")
    nifty_close = 0
else:
    for col in ["vwap", "oi"]:
        if col not in bars.columns:
            bars[col] = 0
    bars = bars[["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap", "oi"]]
    upsert_candles(bars)
    nifty_close = float(bars.iloc[-1]["close"])
    first_ts = str(bars.iloc[0]["timestamp"])
    last_ts = str(bars.iloc[-1]["timestamp"])
    print(f"NIFTY-I: upserted {len(bars)} candles  [{first_ts} → {last_ts}]  last={nifty_close:.1f}")

# 2. ATM option candles
if nifty_close > 0:
    atm = round(nifty_close / 50) * 50
    expiry = get_nearest_expiry(today)
    if not expiry:
        print("WARNING: No expiry found, skipping options")
        sys.exit(0)
    exp_code = expiry.strftime("%y%m%d")
    print(f"\nATM={atm}, Expiry={expiry}")
    expected_bars = max(1, int((end_dt - day_start).total_seconds() / 60))

    for delta in range(-3, 4):
        strike = atm + delta * 50
        for opt in ["CE", "PE"]:
            sym = f"NIFTY{exp_code}{strike}{opt}"
            chk = read_sql(
                "SELECT COUNT(*) as cnt FROM minute_candles WHERE symbol=:s AND timestamp::date=:d",
                {"s": sym, "d": today.isoformat()},
            )
            cnt = int(chk.iloc[0]["cnt"]) if not chk.empty else 0
            if cnt >= expected_bars * 0.8:
                print(f"  {sym}: already has {cnt}/{expected_bars} bars, skipping")
                continue
            try:
                ob = td.fetch_historical_bars(sym, day_start, end_dt, interval="1min")
                if not ob.empty:
                    for col in ["vwap", "oi"]:
                        if col not in ob.columns:
                            ob[col] = 0
                    ob = ob[["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap", "oi"]]
                    upsert_candles(ob)
                    print(f"  {sym}: upserted {len(ob)} bars (had {cnt})")
                else:
                    print(f"  {sym}: no data returned")
                time.sleep(1.1)
            except Exception as e:
                print(f"  {sym}: ERROR {e}")

print("\nDone.")
