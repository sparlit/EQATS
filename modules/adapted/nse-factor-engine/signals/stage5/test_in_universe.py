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
Quick inspect/test for signals/stage5/metrics/in_universe.py
Run standalone on EC2 to verify before wiring into the assembler.

Matches on RUN_DATE (filename), not T -- per locked convention.
"""
import glob
import re
import sys

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"
sys.path.insert(0, BASE + "signals/stage5/metrics")
from in_universe import compute as compute_in_universe

signals_files = glob.glob(BASE + "signals/final/momentum_signals_final_*.parquet")
signals_files = [f for f in signals_files if "_pre_stage4_backup" not in f]

date_re = re.compile(r"momentum_signals_final_(\d{8})\.parquet$")
dated = []
for f in signals_files:
    m = date_re.search(f)
    if m:
        dated.append((m.group(1), f))

assert dated, "No signals files found"
dated.sort(key=lambda x: pd.Timestamp(day=int(x[0][:2]), month=int(x[0][2:4]), year=int(x[0][4:])))
run_date_str, SIGNALS_PATH = dated[-1]

print(f"Using signals file run_date: {run_date_str}")
print(f"Signals path: {SIGNALS_PATH}")

signals = pd.read_parquet(SIGNALS_PATH)
print(f"Signals shape: {signals.shape}")
print(f"as_of_date inside file: {signals['as_of_date'].iloc[0]}")

result = compute_in_universe(signals, run_date_str, BASE)

print("\n--- Result shape ---")
print(result.shape)

print("\n--- Columns ---")
print(list(result.columns))

print("\n--- in_universe value counts ---")
print(result["in_universe"].value_counts(dropna=False).to_string())

print("\n--- passes_mktcap value counts ---")
print(result["passes_mktcap"].value_counts(dropna=False).to_string())

print("\n--- passes_adtv value counts ---")
print(result["passes_adtv"].value_counts(dropna=False).to_string())

print("\n--- Sample rows ---")
print(result.head(10).to_string())

merged = signals.merge(result, on="symbol", how="left")
print("\n--- Post-merge shape (before filter) ---")
print(merged.shape)
print(f"Nulls in in_universe after merge: {merged['in_universe'].isnull().sum()}")

filtered = merged[merged["in_universe"]]
print("\n--- Post-filter shape (in_universe == True) ---")
print(filtered.shape)
print(f"Investable universe size: {len(filtered)}")
