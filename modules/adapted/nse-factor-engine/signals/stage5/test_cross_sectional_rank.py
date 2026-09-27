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


"""
Quick inspect/test for signals/stage5/metrics/cross_sectional_rank.py
Chains off in_universe.py output (in-universe-filtered signals).
"""
import glob
import re
import sys

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"
sys.path.insert(0, BASE + "signals/stage5/metrics")
from cross_sectional_rank import RANK_METRICS
from cross_sectional_rank import compute as compute_rank
from in_universe import compute as compute_in_universe

signals_files = glob.glob(BASE + "signals/final/momentum_signals_final_*.parquet")
signals_files = [f for f in signals_files if "_pre_stage4_backup" not in f]

date_re = re.compile(r"momentum_signals_final_(\d{8})\.parquet$")
dated = []
for f in signals_files:
    m = date_re.search(f)
    if m:
        dated.append((m.group(1), f))

dated.sort(key=lambda x: pd.Timestamp(day=int(x[0][:2]), month=int(x[0][2:4]), year=int(x[0][4:])))
run_date_str, SIGNALS_PATH = dated[-1]

print(f"Using signals file run_date: {run_date_str}")
signals = pd.read_parquet(SIGNALS_PATH)
print(f"Signals shape: {signals.shape}")

universe_result = compute_in_universe(signals, run_date_str, BASE)
merged = signals.merge(universe_result, on="symbol", how="left")
in_universe_signals = merged[merged["in_universe"]].copy()
print(f"In-universe signals shape: {in_universe_signals.shape}")

rank_result = compute_rank(in_universe_signals)

print("\n--- Result shape ---")
print(rank_result.shape)

print("\n--- Columns ---")
print(list(rank_result.columns))

print("\n--- Null check ---")
print(rank_result.isnull().sum().to_string())

print("\n--- Rank range check (should be 1 to N for each metric) ---")
for metric in RANK_METRICS:
    col = f"rank_{metric}"
    print(f"{col}: min={rank_result[col].min()}, max={rank_result[col].max()}, n_unique={rank_result[col].nunique()}")

print("\n--- Spot check: rank_ret_12m1m == 1 ---")
check = in_universe_signals.merge(rank_result, on="symbol")
top1 = check[check["rank_ret_12m1m"] == 1][["symbol", "ret_12m1m", "rank_ret_12m1m"]]
print(top1.to_string())
actual_max_symbol = check.loc[check["ret_12m1m"].idxmax(), "symbol"]
print(f"Actual max ret_12m1m symbol: {actual_max_symbol}")
assert actual_max_symbol in top1["symbol"].values, "MISMATCH: rank 1 does not match actual max"
print("PASS: rank 1 matches actual max value")

print("\n--- Sample rows ---")
print(rank_result.head(10).to_string())
