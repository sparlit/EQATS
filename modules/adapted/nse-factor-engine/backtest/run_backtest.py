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
Backtest Master Orchestrator — Phase 6

Runs the full backtest pipeline end-to-end:
    1. Verify all 511 signal files exist
    2. Run simulation (511 Fridays × 25 cells)
    3. Compute metrics
    4. Write 3 output files

Output files (dated with IST run date):
    backtest/results/backtest_results_{DDMMYYYY}.parquet
    backtest/results/backtest_weekly_returns_{DDMMYYYY}.parquet
    backtest/results/backtest_portfolio_activity_{DDMMYYYY}.parquet
"""

import gc
import os
import sys
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/ec2-user/nse-factor-engine")

from backtest.metrics.compute_metrics import run as compute_metrics
from backtest.simulation.portfolio import PortfolioState
from backtest.strategies.config import CELLS
from backtest.strategies.engine import get_portfolio

BASE = "/home/ec2-user/nse-factor-engine/backtest"
SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"
INITIAL_CAPITAL = 10_000_000.0

os.makedirs(RESULTS_DIR, exist_ok=True)

# IST run date — used for output filenames
run_date = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d%m%Y")
WR_PATH = f"{RESULTS_DIR}/backtest_weekly_returns_{run_date}.parquet"
ACT_PATH = f"{RESULTS_DIR}/backtest_portfolio_activity_{run_date}.parquet"
RES_PATH = f"{RESULTS_DIR}/backtest_results_{run_date}.parquet"

t_total = time.time()

# ── Step 1: Verify signal files ───────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Verifying signal files ...")
prices = pd.read_parquet(PRICES_PATH)
all_dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
fridays = all_dates[all_dates.dayofweek == 4]
valid = [f for f in fridays if len(all_dates[all_dates < f]) >= 252]

missing = []
for T in valid:
    date_str = pd.Timestamp(T).strftime("%d%m%Y")
    if not os.path.exists(f"{SIG_DIR}/signals_{date_str}.parquet"):
        missing.append(T.date())

if missing:
    print(f"ERROR: {len(missing)} signal files missing: {missing[:5]}...")
    sys.exit(1)

print(f"  Signal files : {len(valid)}/511 present ✓")

# ── Step 2: Run simulation ────────────────────────────────────────────────────
print()
print("STEP 2 — Running simulation ...")

# check if already run today
if os.path.exists(WR_PATH) and os.path.exists(ACT_PATH):
    print(f"  Simulation outputs already exist for run_date={run_date} — loading.")
    weekly_df = pd.read_parquet(WR_PATH)
    activity_df = pd.read_parquet(ACT_PATH)
else:
    print("Indexing close prices by date ...")
    prices_by_date = {
        date: grp.set_index("symbol")["close"].to_dict() for date, grp in prices.groupby("date")
    }

    bench = pd.read_parquet(BENCH_PATH).set_index("date")["close"]

    cell_states = {f"{g}_{c}": PortfolioState(INITIAL_CAPITAL) for g, c in CELLS}
    portfolio_values = {f"{g}_{c}": [] for g, c in CELLS}
    all_activity = []

    t_sim = time.time()
    for i, T in enumerate(valid):
        date_str = pd.Timestamp(T).strftime("%d%m%Y")
        signals = pd.read_parquet(f"{SIG_DIR}/signals_{date_str}.parquet")
        px_T = prices_by_date.get(T, {})

        for gate_id, score_id in CELLS:
            cell_id = f"{gate_id}_{score_id}"
            # incumbents = symbols currently held by this cell (from prior week)
            incumbent_symbols = set(cell_states[cell_id].holdings.keys())
            port_df = get_portfolio(
                gate_id, score_id, signals, verbose=False, incumbent_symbols=incumbent_symbols
            )
            top25 = port_df["symbol"].tolist() if not port_df.empty else []
            pv, act = cell_states[cell_id].rebalance(top25, px_T, pd.Timestamp(T), cell_id)
            portfolio_values[cell_id].append((T, pv))
            all_activity.extend(act)

        gc.collect()

        if (i + 1) % 50 == 0 or i == 0 or (i + 1) == len(valid):
            elapsed = time.time() - t_sim
            remaining = elapsed / (i + 1) * (len(valid) - i - 1)
            print(
                f"  [{i + 1:03d}/{len(valid)}] T={T.date()} | "
                f"elapsed={elapsed / 60:.1f}min | ETA={remaining / 60:.1f}min",
                flush=True,
            )

    # assemble weekly returns
    friday_dates = [t for t, _ in portfolio_values[list(cell_states.keys())[0]]]
    weekly_df = pd.DataFrame({"friday_date": friday_dates})

    for cell_id, vals in portfolio_values.items():
        pv = pd.Series([v for _, v in vals])
        wr = pv.pct_change().values
        wr[0] = 0.0
        weekly_df[cell_id] = wr

    bench_aligned = [bench.get(T, np.nan) for T in friday_dates]
    bench_series = pd.Series(bench_aligned).pct_change()
    bench_series.iloc[0] = 0.0
    weekly_df["benchmark"] = bench_series.values

    activity_df = pd.DataFrame(all_activity)

    weekly_df.to_parquet(WR_PATH, index=False)
    activity_df.to_parquet(ACT_PATH, index=False)
    print(f"  Saved: {WR_PATH}")
    print(f"  Saved: {ACT_PATH}")
    print(f"  Simulation time: {(time.time() - t_sim) / 60:.1f} min")

print(f"  Weekly returns shape : {weekly_df.shape}")
print(f"  Activity log shape   : {activity_df.shape}")

# ── Step 3: Compute metrics ───────────────────────────────────────────────────
print()
print("STEP 3 — Computing metrics ...")
results_df, bench_metrics = compute_metrics(WR_PATH)

# attach benchmark metrics as last row
bench_row = {
    "cell_id": "BENCHMARK",
    "gate_variant": "-",
    "score_variant": "-",
    "cagr": bench_metrics["cagr"],
    "sharpe": bench_metrics["sharpe"],
    "sortino": bench_metrics["sortino"],
    "max_dd": bench_metrics["max_dd"],
    "dd_recovery_weeks": bench_metrics["dd_recovery_weeks"],
    "deflated_sharpe_margin": np.nan,
    "sharpe_significant": False,
    "alpha": 0.0,
    "benchmark_cagr": bench_metrics["cagr"],
    "total_weeks": bench_metrics["weeks_positive"]
    + bench_metrics["weeks_dd_0_5"]
    + bench_metrics["weeks_dd_5_10"]
    + bench_metrics["weeks_dd_10_20"]
    + bench_metrics["weeks_dd_gt20"],
    "initial_capital": INITIAL_CAPITAL,
    "rf_rate": 0.07,
    "weeks_positive": bench_metrics["weeks_positive"],
    "weeks_dd_0_5": bench_metrics["weeks_dd_0_5"],
    "weeks_dd_5_10": bench_metrics["weeks_dd_5_10"],
    "weeks_dd_10_20": bench_metrics["weeks_dd_10_20"],
    "weeks_dd_gt20": bench_metrics["weeks_dd_gt20"],
}
results_df = pd.concat([results_df, pd.DataFrame([bench_row])], ignore_index=True)

# ── Step 4: Save results ──────────────────────────────────────────────────────
print()
print("STEP 4 — Saving results ...")
results_df.to_parquet(RES_PATH, index=False)
print(f"  Saved: {RES_PATH}")

# ── Final summary ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("BACKTEST COMPLETE")
print(f"Run date       : {run_date}")
print(f"Total time     : {(time.time() - t_total) / 60:.1f} min")
print()
print("Output files:")
for path in [RES_PATH, WR_PATH, ACT_PATH]:
    print(f"  {path} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
print()
print("Top 5 cells by Sharpe:")
top5 = results_df[results_df["cell_id"] != "BENCHMARK"].nlargest(5, "sharpe")
print(top5[["cell_id", "cagr", "sharpe", "sortino", "max_dd", "alpha"]].to_string(index=False))
print()
print("Benchmark:")
print(
    f"  CAGR={bench_metrics['cagr']:.2%} Sharpe={bench_metrics['sharpe']:.2f} "
    f"MaxDD={bench_metrics['max_dd']:.2%}"
)
print("=" * 60)
