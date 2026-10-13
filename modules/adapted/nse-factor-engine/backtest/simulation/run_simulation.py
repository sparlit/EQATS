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
Backtest Simulation — Run 511 Fridays × 25 Cells

For each cell, maintains a separate PortfolioState across all 511 Fridays.
Produces:
    - weekly_returns dict: {cell_id: [(friday_date, portfolio_value), ...]}
    - activity_rows list: position-level log across all cells and Fridays
"""

import gc
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/ec2-user/nse-factor-engine")

from backtest.simulation.portfolio import PortfolioState
from backtest.strategies.config import CELLS
from backtest.strategies.engine import get_portfolio

BASE = "/home/ec2-user/nse-factor-engine/backtest"
SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
INITIAL_CAPITAL = 10_000_000.0

# ── Load inputs ───────────────────────────────────────────────────────────────
print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH)
print(f"  prices shape : {prices.shape}")

print("Loading benchmark ...")
bench = pd.read_parquet(BENCH_PATH).set_index("date")["close"]

# ── Valid Fridays ─────────────────────────────────────────────────────────────
all_dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
fridays = all_dates[all_dates.dayofweek == 4]
valid = [f for f in fridays if len(all_dates[all_dates < f]) >= 252]
print(f"Valid Fridays  : {len(valid)} ({valid[0].date()} → {valid[-1].date()})")

# ── Pre-index close prices by date ────────────────────────────────────────────
print("Indexing close prices by date ...")
prices_by_date = {
    date: grp.set_index("symbol")["close"].to_dict() for date, grp in prices.groupby("date")
}
print(f"  Indexed {len(prices_by_date)} dates")
print()

# ── Initialise one PortfolioState per cell ────────────────────────────────────
cell_states = {f"{g}_{c}": PortfolioState(initial_capital=INITIAL_CAPITAL) for g, c in CELLS}

# storage
portfolio_values = {cell_id: [] for cell_id in cell_states}
all_activity = []

# ── Main loop: Friday × Cell ──────────────────────────────────────────────────
t_start = time.time()

for i, T in enumerate(valid):
    date_str = pd.Timestamp(T).strftime("%d%m%Y")
    sig_path = f"{SIG_DIR}/signals_{date_str}.parquet"

    if not os.path.exists(sig_path):
        print(f"MISSING signals for {T.date()} — skipping", flush=True)
        continue

    signals = pd.read_parquet(sig_path)
    px_T = prices_by_date.get(T, {})

    for gate_id, score_id in CELLS:
        cell_id = f"{gate_id}_{score_id}"
        state = cell_states[cell_id]

        # get top-25
        port_df = get_portfolio(gate_id, score_id, signals, verbose=False)
        top25 = port_df["symbol"].tolist() if not port_df.empty else []

        # rebalance
        port_value, activity = state.rebalance(top25, px_T, pd.Timestamp(T), cell_id)

        portfolio_values[cell_id].append((T, port_value))
        all_activity.extend(activity)

    gc.collect()

    if (i + 1) % 50 == 0 or i == 0 or (i + 1) == len(valid):
        elapsed = time.time() - t_start
        remaining = elapsed / (i + 1) * (len(valid) - i - 1)
        print(
            f"[{i + 1:03d}/{len(valid)}] T={T.date()} | "
            f"elapsed={elapsed / 60:.1f}min | ETA={remaining / 60:.1f}min",
            flush=True,
        )

print()

# ── Assemble weekly returns DataFrame ─────────────────────────────────────────
print("Assembling weekly returns ...")
weekly_df = pd.DataFrame(
    {"friday_date": [t for t, _ in portfolio_values[list(cell_states.keys())[0]]]}
)

for cell_id, vals in portfolio_values.items():
    pv = pd.Series([v for _, v in vals])
    weekly_df[cell_id] = pv.pct_change().values
    weekly_df.loc[0, cell_id] = 0.0  # week 1: no prior value, return = 0

# benchmark weekly return
bench_aligned = []
for T in [t for t, _ in portfolio_values[list(cell_states.keys())[0]]]:
    bench_aligned.append(bench.get(T, np.nan))
bench_series = pd.Series(bench_aligned)
weekly_df["benchmark"] = bench_series.pct_change().values
weekly_df.loc[0, "benchmark"] = 0.0

# ── Assemble activity DataFrame ───────────────────────────────────────────────
print("Assembling activity log ...")
activity_df = pd.DataFrame(all_activity)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"Weekly returns shape   : {weekly_df.shape}")
print(f"Activity log shape     : {activity_df.shape}")
print(f"Total time             : {(time.time() - t_start) / 60:.1f} min")
print()

# spot check
for cell_id in ["G1_C1", "G5_C5"]:
    rets = weekly_df[cell_id].dropna()
    cum = (1 + rets).prod() - 1
    print(f"{cell_id}: mean_wk={rets.mean():.4f} std={rets.std():.4f} cum={cum:.4f}")
print(f"Benchmark: cum={(1 + weekly_df['benchmark'].dropna()).prod() - 1:.4f}")
print("=" * 60)

# return for use by run_backtest.py
if __name__ == "__main__":
    # save to parquet for inspection
    from datetime import datetime

    import pytz

    run_date = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d%m%Y")
    os.makedirs(f"{BASE}/results", exist_ok=True)
    wr_path = f"{BASE}/results/backtest_weekly_returns_{run_date}.parquet"
    act_path = f"{BASE}/results/backtest_portfolio_activity_{run_date}.parquet"
    weekly_df.to_parquet(wr_path, index=False)
    activity_df.to_parquet(act_path, index=False)
    print(f"Saved: {wr_path}")
    print(f"Saved: {act_path}")
    print(f"Weekly returns size  : {os.path.getsize(wr_path) / 1024:.1f} KB")
    print(f"Activity log size    : {os.path.getsize(act_path) / 1024 / 1024:.1f} MB")
