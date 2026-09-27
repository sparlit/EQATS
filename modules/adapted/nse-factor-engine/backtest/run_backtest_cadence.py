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
Backtest Cadence Variants — W2 (biweekly) and W4 (monthly) rebalance.
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

from backtest.metrics.compute_metrics import compute_benchmark_metrics
from backtest.metrics.compute_metrics import run as compute_metrics
from backtest.simulation.portfolio import PortfolioState
from backtest.strategies.config import CELLS
from backtest.strategies.engine import get_portfolio

BASE = "/home/ec2-user/nse-factor-engine/backtest"
SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"
INITIAL_CAP = 10_000_000.0
RUN_TAG = "09072026"

os.makedirs(RESULTS_DIR, exist_ok=True)

print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH)
all_dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
fridays = all_dates[all_dates.dayofweek == 4]
valid = [f for f in fridays if len(all_dates[all_dates < f]) >= 252]
print(f"Valid Fridays: {len(valid)}")

print("Indexing close prices by date ...")
prices_by_date = {date: grp.set_index("symbol")["close"].to_dict() for date, grp in prices.groupby("date")}

bench = pd.read_parquet(BENCH_PATH).set_index("date")["close"]


def run_cadence(cadence: int, tag: str):
    WR_PATH = f"{RESULTS_DIR}/backtest_weekly_returns_{tag}_{RUN_TAG}.parquet"
    ACT_PATH = f"{RESULTS_DIR}/backtest_portfolio_activity_{tag}_{RUN_TAG}.parquet"
    RES_PATH = f"{RESULTS_DIR}/backtest_results_{tag}_{RUN_TAG}.parquet"

    print(f"\n{'=' * 60}")
    print(f"CADENCE {tag} — rebalance every {cadence} weeks")
    print(f"Total Fridays : {len(valid)}")
    expected_rebal = len([i for i in range(len(valid)) if i % cadence == 0])
    print(f"Expected rebalances: {expected_rebal}")
    print(f"{'=' * 60}")

    cell_states = {f"{g}_{c}": PortfolioState(INITIAL_CAP) for g, c in CELLS}
    portfolio_values = {f"{g}_{c}": [] for g, c in CELLS}
    all_activity = []
    rebal_count = 0

    t_sim = time.time()
    for i, T in enumerate(valid):
        is_rebalance = i % cadence == 0
        if is_rebalance:
            rebal_count += 1

        date_str = pd.Timestamp(T).strftime("%d%m%Y")
        px_T = prices_by_date.get(T, {})

        if is_rebalance:
            sig_path = f"{SIG_DIR}/signals_{date_str}.parquet"
            signals = pd.read_parquet(sig_path)
        else:
            signals = None

        for gate_id, score_id in CELLS:
            cell_id = f"{gate_id}_{score_id}"
            state = cell_states[cell_id]

            if is_rebalance:
                incumbent_symbols = set(state.holdings.keys())
                port_df = get_portfolio(gate_id, score_id, signals, verbose=False, incumbent_symbols=incumbent_symbols)
                top_n = port_df["symbol"].tolist() if not port_df.empty else []
            else:
                top_n = list(state.holdings.keys())

            pv, act = state.rebalance(top_n, px_T, pd.Timestamp(T), cell_id)
            portfolio_values[cell_id].append((T, pv))
            all_activity.extend(act)

        gc.collect()

        # Print every 5 weeks
        if (i % 5 == 0) or (i + 1 == len(valid)):
            elapsed = time.time() - t_sim
            remaining = elapsed / (i + 1) * (len(valid) - i - 1)
            status = f"REBAL #{rebal_count:03d}" if is_rebalance else "hold        "
            print(
                f"  [w={i + 1:03d}] {T.date()} {status} | "
                f"rebal_so_far={rebal_count} | "
                f"elapsed={elapsed / 60:.1f}m ETA={remaining / 60:.1f}m",
                flush=True,
            )

    print(f"\n  Total weeks processed : {len(valid)}")
    print(f"  Total rebalances done : {rebal_count} (expected {expected_rebal})")

    # ── Assemble weekly returns ────────────────────────────────────────────────
    friday_dates = [t for t, _ in portfolio_values[next(iter(cell_states.keys()))]]
    weekly_df = pd.DataFrame({"friday_date": friday_dates})

    for cell_id, vals in portfolio_values.items():
        pv = pd.Series([v for _, v in vals])
        wr = pv.pct_change().values
        wr[0] = 0.0
        weekly_df[cell_id] = wr

    bench_aligned = [bench.get(T, np.nan) for T in friday_dates]
    bench_s = pd.Series(bench_aligned).pct_change()
    bench_s.iloc[0] = 0.0
    weekly_df["benchmark"] = bench_s.values

    activity_df = pd.DataFrame(all_activity)

    # Verify activity row counts
    sells = activity_df[activity_df["action"] == "SELL"]
    buys = activity_df[activity_df["action"] == "BUY"]
    holds = activity_df[activity_df["action"] == "HOLD"]
    print(f"  Activity rows — BUY:{len(buys)} SELL:{len(sells)} HOLD:{len(holds)} TOTAL:{len(activity_df)}")

    # Verify portfolio size per week for G6_C6
    g6c6_act = activity_df[(activity_df["cell_id"] == "G6_C6") & (activity_df["action"].isin(["BUY", "HOLD"]))]
    port_sizes = g6c6_act.groupby("friday_date")["symbol"].nunique()
    print(f"  G6_C6 holdings per week — mean:{port_sizes.mean():.1f} min:{port_sizes.min()} max:{port_sizes.max()}")

    # Verify rebalance dates for G6_C6
    rebal_dates = activity_df[(activity_df["cell_id"] == "G6_C6") & (activity_df["action"] == "BUY")][
        "friday_date"
    ].unique()
    print(f"  G6_C6 BUY events on {len(rebal_dates)} distinct dates")

    weekly_df.to_parquet(WR_PATH, index=False)
    activity_df.to_parquet(ACT_PATH, index=False)
    print(f"  Saved: {WR_PATH}")
    print(f"  Saved: {ACT_PATH}")
    print(f"  Sim time: {(time.time() - t_sim) / 60:.1f} min")

    # ── Metrics ───────────────────────────────────────────────────────────────
    results_df, bench_metrics = compute_metrics(WR_PATH)

    bench_row = {
        "cell_id": "BENCHMARK",
        "gate_variant": "-",
        "score_variant": "-",
        "cagr": bench_metrics["cagr"],
        "sharpe": bench_metrics["sharpe"],
        "sortino": bench_metrics["sortino"],
        "max_dd": bench_metrics["max_dd"],
        "dd_recovery_weeks": bench_metrics["dd_recovery_weeks"],
        "deflated_sharpe": np.nan,
        "sharpe_significant": False,
        "alpha": 0.0,
        "benchmark_cagr": bench_metrics["cagr"],
        "total_weeks": len(weekly_df),
        "initial_capital": INITIAL_CAP,
        "rf_rate": 0.07,
        "weeks_positive": bench_metrics["weeks_positive"],
        "weeks_dd_0_5": bench_metrics["weeks_dd_0_5"],
        "weeks_dd_5_10": bench_metrics["weeks_dd_5_10"],
        "weeks_dd_10_20": bench_metrics["weeks_dd_10_20"],
        "weeks_dd_gt20": bench_metrics["weeks_dd_gt20"],
    }
    results_df = pd.concat([results_df, pd.DataFrame([bench_row])], ignore_index=True)
    results_df.to_parquet(RES_PATH, index=False)

    g6c6 = results_df[results_df["cell_id"] == "G6_C6"].iloc[0]
    print(f"  [{tag}] G6_C6 — CAGR={g6c6.cagr:.2%} Sharpe={g6c6.sharpe:.2f} MaxDD={g6c6.max_dd:.2%}")
    print(f"  Saved metrics: {RES_PATH}")

    return results_df


t_total = time.time()
for cadence, tag in [(2, "W2"), (4, "W4")]:
    run_cadence(cadence, tag)

print(f"\nTotal time: {(time.time() - t_total) / 60:.1f} min")
print("DONE")
