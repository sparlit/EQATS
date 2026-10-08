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


import gc
import os
import sys
import time
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/ec2-user/nse-factor-engine")
from backtest.pipeline.compute_signals import compute_signals

BASE = "/home/ec2-user/nse-factor-engine/backtest"
OUT_DIR = f"{BASE}/signals/historical"
os.makedirs(OUT_DIR, exist_ok=True)

print("Loading prices ...")
prices = pd.read_parquet(f"{BASE}/data/prices_backtest.parquet")
meta = pd.read_parquet(f"{BASE}/data/universe_metadata_backtest.parquet")

all_dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
fridays = all_dates[all_dates.dayofweek == 4]
valid = [f for f in fridays if len(all_dates[all_dates < f]) >= 252]

print(f"Valid Fridays : {len(valid)}")
print(f"Already done  : {len(os.listdir(OUT_DIR))}")
print()

total, done, skipped, failed = len(valid), 0, 0, []
t_start = time.time()

for i, T in enumerate(valid):
    date_str = pd.Timestamp(T).strftime("%d%m%Y")
    out_path = f"{OUT_DIR}/signals_{date_str}.parquet"

    if os.path.exists(out_path):
        skipped += 1
        continue

    t0 = time.time()
    try:
        # pre-slice: only pass 300 trading days ending at T
        t_pos = all_dates.get_loc(T)
        start_idx = max(0, t_pos - 300)
        start_date = all_dates[start_idx]
        px_window = prices[(prices["date"] >= start_date) & (prices["date"] <= T)]

        df = compute_signals(px_window, meta, pd.Timestamp(T))
        df.to_parquet(out_path, index=False)
        info = f"rows={len(df)} in_universe={df['in_universe'].sum()}"

        del df, px_window
        gc.collect()

        done += 1
        elapsed = time.time() - t0
        total_elapsed = time.time() - t_start
        avg = total_elapsed / done
        remaining = (total - done - skipped) * avg
        print(
            f"[{i + 1:03d}/{total}] T={T.date()} | {info} | {elapsed:.1f}s | ETA {remaining / 60:.1f}min",
            flush=True,
        )

    except Exception as e:
        failed.append((T.date(), str(e)))
        print(f"[{i + 1:03d}/{total}] T={T.date()} FAILED: {e}", flush=True)
        gc.collect()

print()
print("=" * 60)
print(f"Total    : {total}")
print(f"Computed : {done}")
print(f"Skipped  : {skipped}")
print(f"Failed   : {len(failed)}")
if failed:
    for d, e in failed:
        print(f"  {d} : {e}")
print(f"Files    : {len(os.listdir(OUT_DIR))}")
print(f"Time     : {(time.time() - t_start) / 60:.1f} min")
print("=" * 60)
