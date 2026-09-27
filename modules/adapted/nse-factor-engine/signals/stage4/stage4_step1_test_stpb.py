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


import sys

import pandas as pd

sys.path.insert(0, "/home/ec2-user/nse-factor-engine/signals/stage4/metrics")
from stpb import compute

BASE = "/home/ec2-user/nse-factor-engine/"
prices = pd.read_parquet(BASE + "data/prices.parquet")
signals = pd.read_parquet(BASE + "signals/final/momentum_signals_final_25062026.parquet")

date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())

result = compute(prices, signals, T, all_dates)

print("shape:", result.shape)
print("nulls:\n", result.isnull().sum())
print()
print(result.describe())
print()
print("VEDL row (watch for split distortion, KI-001):")
print(result[result["symbol"] == "VEDL"])
print()
print("Sample:\n", result.head(10))
