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
Friday Signal -> Monday Open Execution — Full Backtest Run

Signal date  : Friday close (signals/historical/, 511 files)
Execute date : next trading day after signal Friday (Monday, or Tuesday if holiday)
Return       : Monday-open[T+1] to Monday-open[T]  (NAV-over-NAV, not price-over-price)

Cell: G6_C6 (Gate=G6, Score=C6)

This is the corrected successor to run_sim_mon_tue_open.py, which unpacks only
2 values from PortfolioState.rebalance() -- a function that returns 3
(portfolio_value_post, portfolio_value_pre, activity) -- and crashes with
ValueError: too many values to unpack. This script unpacks all 3.

Outputs:
  backtest/results/backtest_G6_C6_weekly_returns_<RUN_DATE>.csv
    columns: signal_friday, exec_date, nav, weekly_ret, cum_ret, benchmark_ret
  backtest/results/backtest_G6_C6_activity_<RUN_DATE>.csv
    full per-symbol BUY/SELL/HOLD activity log, all weeks
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
from backtest.strategies.engine import get_portfolio

BASE = "/home/ec2-user/nse-factor-engine/backtest"
FRI_SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"

CELL_ID = "G6_C6"
GATE_ID = "G6"
SCORE_ID = "C6"
INITIAL_CAPITAL = 10_000_000.0
RUN_DATE = time.strftime("%d%m%Y")

N_WEEKS_LIMIT = 600  # >= 511, so this runs the full historical set. Lower to
# e.g. 3 to reproduce the earlier manual-verification trace.

os.makedirs(RESULTS_DIR, exist_ok=True)


def parse_date(fname):
    d = fname.replace("signals_", "").replace(".parquet", "")
    return pd.Timestamp(f"{d[4:8]}-{d[2:4]}-{d[0:2]}")


print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH)
print(f"  shape      : {prices.shape}")
print(f"  date range : {prices['date'].min().date()} -> {prices['date'].max().date()}")

open_by_date = {
    pd.Timestamp(date): grp.set_index("symbol")["open"].to_dict()
    for date, grp in prices.groupby("date")
}
all_trading_days = sorted(open_by_date.keys())
print(f"  trading days indexed: {len(all_trading_days)}")
del prices
gc.collect()

print("Loading benchmark ...")
bench = pd.read_parquet(BENCH_PATH).set_index("date")["close"]
bench.index = pd.DatetimeIndex(bench.index)


def next_trading_day(dt):
    for td in all_trading_days:
        if td > dt:
            return td
    return None


print("\nBuilding Friday-signal -> Monday-open week pairs ...")
fri_files = sorted(
    f
    for f in os.listdir(FRI_SIG_DIR)
    if f.startswith("signals_")
    and f.endswith(".parquet")
    and os.path.isfile(os.path.join(FRI_SIG_DIR, f))
)

mon_pairs = []
for fname in fri_files:
    sig_date = parse_date(fname)
    exec_date = next_trading_day(sig_date)
    if exec_date and open_by_date.get(exec_date):
        mon_pairs.append((sig_date, exec_date, os.path.join(FRI_SIG_DIR, fname)))
mon_pairs.sort(key=lambda x: x[1])
mon_pairs = mon_pairs[:N_WEEKS_LIMIT]

print(f"  pairs : {len(mon_pairs)}")
print(
    f"  first : sig={mon_pairs[0][0].date()} exec={mon_pairs[0][1].date()} ({mon_pairs[0][1].day_name()})"
)
print(
    f"  last  : sig={mon_pairs[-1][0].date()} exec={mon_pairs[-1][1].date()} ({mon_pairs[-1][1].day_name()})"
)

print(f"\n{'=' * 70}")
print(f"RUNNING: fri_signal_mon_open  ({len(mon_pairs)} weeks)  cell={CELL_ID}")
print(f"{'=' * 70}")

state = PortfolioState(initial_capital=INITIAL_CAPITAL)
nav_path = []
all_activity = []
t0 = time.time()

for i, (sig_date, exec_date, sig_path) in enumerate(mon_pairs):
    signals = pd.read_parquet(sig_path)
    incumbent_symbols = set(state.holdings.keys())

    port_df = get_portfolio(
        GATE_ID, SCORE_ID, signals, verbose=False, incumbent_symbols=incumbent_symbols
    )
    top25 = port_df["symbol"].tolist() if not port_df.empty else []

    meta_cols = [c for c in ["symbol", "final_rank", "composite_score"] if c in port_df.columns]
    meta_df = port_df[meta_cols].set_index("symbol") if not port_df.empty else pd.DataFrame()

    exec_px = open_by_date[exec_date]

    # FIX applied here: unpack all 3 return values from rebalance()
    port_value_post, port_value_pre, activity = state.rebalance(top25, exec_px, exec_date, CELL_ID)

    for row in activity:
        sym = row["symbol"]
        if not meta_df.empty and sym in meta_df.index:
            row["final_rank"] = (
                meta_df.loc[sym, "final_rank"] if "final_rank" in meta_df.columns else np.nan
            )
            row["composite_score"] = (
                meta_df.loc[sym, "composite_score"]
                if "composite_score" in meta_df.columns
                else np.nan
            )
        else:
            row["final_rank"] = np.nan
            row["composite_score"] = np.nan
        row["signal_date"] = sig_date

    nav_path.append((sig_date, exec_date, port_value_pre, port_value_post))
    all_activity.extend(activity)

    if (i + 1) % 50 == 0 or i == 0 or (i + 1) == len(mon_pairs):
        elapsed = time.time() - t0
        remaining = elapsed / (i + 1) * (len(mon_pairs) - i - 1) if i else 0
        print(
            f"  [{i + 1:03d}/{len(mon_pairs)}] sig={sig_date.date()} exec={exec_date.date()} "
            f"NAV=Rs{port_value_post / 1e6:.3f}M | {elapsed:.0f}s elapsed {remaining:.0f}s ETA",
            flush=True,
        )

    gc.collect()

# ---- Weekly returns, cum_ret, benchmark_ret ----
exec_dates = [d for _, d, _, _ in nav_path]
navs = [v_post for _, _, _, v_post in nav_path]

nav_s = pd.Series(navs)
wrets = nav_s.pct_change().values
wrets[0] = 0.0
cum_ret = (1 + pd.Series(wrets)).cumprod() - 1

bm_vals = []
for dt in exec_dates:
    bv = bench.get(dt, np.nan)
    if pd.isna(bv):
        prior = bench[:dt]
        bv = prior.iloc[-1] if len(prior) else np.nan
    bm_vals.append(bv)
bm_ret = pd.Series(bm_vals).pct_change()
bm_ret.iloc[0] = 0.0

weekly_df = pd.DataFrame(
    {
        "signal_friday": [d for d, _, _, _ in nav_path],
        "exec_date": exec_dates,
        "nav": navs,
        "weekly_ret": wrets,
        "cum_ret": cum_ret.values,
        "benchmark_ret": bm_ret.values,
    }
)

activity_df = pd.DataFrame(all_activity)

wr_path = f"{RESULTS_DIR}/backtest_G6_C6_weekly_returns_{RUN_DATE}.csv"
act_path = f"{RESULTS_DIR}/backtest_G6_C6_activity_{RUN_DATE}.csv"
weekly_df.to_csv(wr_path, index=False)
activity_df.to_csv(act_path, index=False)

print(f"\n  weekly_returns -> {wr_path} ({os.path.getsize(wr_path) / 1024:.0f} KB)")
print(f"  activity_log   -> {act_path} ({os.path.getsize(act_path) / 1024 / 1024:.2f} MB)")

# ---- Performance stats ----
rets = weekly_df["weekly_ret"].iloc[1:].dropna()
cum = (1 + rets).prod() - 1
ny = len(rets) / 52
cagr = (1 + cum) ** (1 / ny) - 1 if ny > 0 else np.nan

rf_annual = 0.07
rf_weekly = (1 + rf_annual) ** (1 / 52) - 1
excess_ret = rets - rf_weekly
sharpe = (excess_ret.mean() / excess_ret.std()) * np.sqrt(52) if excess_ret.std() > 0 else np.nan

nav_series = weekly_df["nav"]
running_max = nav_series.cummax()
drawdown = (nav_series - running_max) / running_max
max_dd = drawdown.min()

# Turnover: fraction of portfolio (by count) replaced per week, averaged
turnover_list = []
for sig_date, grp in activity_df.groupby("signal_date"):
    n_buy = (grp["action"] == "BUY").sum()
    n_total = grp["symbol"].nunique()
    if n_total > 0:
        turnover_list.append(n_buy / n_total)
avg_turnover = np.mean(turnover_list) if turnover_list else np.nan

print(f"\n{'=' * 70}")
print(f"PERFORMANCE SUMMARY [{CELL_ID}]")
print(f"{'=' * 70}")
print(f"  weeks            : {len(rets)}")
print(f"  full-period CAGR : {cagr:.2%}")
print(f"  Sharpe (RF=7%)   : {sharpe:.3f}")
print(f"  Max Drawdown     : {max_dd:.2%}")
print(f"  Avg Turnover     : {avg_turnover:.2%}")
print(f"  NAV start        : Rs{navs[0] / 1e6:.4f}M")
print(f"  NAV end          : Rs{navs[-1] / 1e6:.3f}M")
print(f"  activity rows    : {len(activity_df)}")
print(f"  total time       : {(time.time() - t0) / 60:.1f} min")
print("\n  Sanity check -- expected G6_C6 CAGR ~23.45%")
print(f"  Actual       -- {cagr:.2%}")
