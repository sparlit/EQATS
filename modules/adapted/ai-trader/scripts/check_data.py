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


"""Quick check of what data we have in the DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.db import read_sql

# Minute candles
summary = read_sql(
    "SELECT MIN(timestamp)::date as first_day, MAX(timestamp)::date as last_day, "
    "COUNT(*) as total_bars, COUNT(DISTINCT timestamp::date) as trading_days "
    "FROM minute_candles WHERE symbol = 'NIFTY-I'"
)
print("=== MINUTE CANDLES (NIFTY-I) ===")
print(summary.to_string(index=False))

monthly = read_sql(
    "SELECT DATE_TRUNC('month', timestamp)::date as month, "
    "COUNT(*) as bars, COUNT(DISTINCT timestamp::date) as days "
    "FROM minute_candles WHERE symbol = 'NIFTY-I' GROUP BY 1 ORDER BY 1"
)
print("\nMonthly breakdown:")
print(monthly.to_string(index=False))

# Tick data
tick_summary = read_sql(
    "SELECT MIN(timestamp)::date as first_day, MAX(timestamp)::date as last_day, "
    "COUNT(*) as total_ticks, COUNT(DISTINCT timestamp::date) as trading_days "
    "FROM tick_data WHERE symbol = 'NIFTY-I'"
)
print("\n=== TICK DATA (NIFTY-I) ===")
print(tick_summary.to_string(index=False))

tick_daily = read_sql(
    "SELECT timestamp::date as day, COUNT(*) as ticks FROM tick_data WHERE symbol = 'NIFTY-I' GROUP BY 1 ORDER BY 1"
)
print("\nTick data by day:")
print(tick_daily.to_string(index=False))

# Check what the current model was trained on
from pathlib import Path

import joblib

macro_path = "models/saved/macro_model.pkl"
if Path(macro_path).exists():
    data = joblib.load(macro_path)
    print("\n=== CURRENT MACRO MODEL ===")
    print(f"Features: {len(data.get('features', []))}")
    print(f"Metrics: {data.get('metrics', {})}")
else:
    print(f"\nNo macro model found at {macro_path}")

strat_dir = Path("models/saved")
strat_files = list(strat_dir.glob("strategy_*.pkl"))
if strat_files:
    print("\n=== STRATEGY MODELS ===")
    for f in strat_files:
        d = joblib.load(f)
        print(f"  {f.name}: features={len(d.get('features', []))}, metrics={d.get('metrics', {})}")
