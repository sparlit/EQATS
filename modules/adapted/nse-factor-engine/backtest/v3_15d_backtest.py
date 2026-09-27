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
MR_M V3_15D Backtest
====================
Bi-weekly (~15 calendar day) rebalance version of V3 (60/40 12m:6m weights).
Scoring, reconstitution, and portfolio mechanics identical to v3_backtest.py.
Only cadence changes: rebalance every ~15 calendar days vs monthly.

Run from repo root:
  cd /home/ec2-user/nse-factor-engine
  python3 backtest/v3_15d_backtest.py
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

# ── Constants ─────────────────────────────────────────────────────────────────
PORTFOLIO_N = 25
FORCED_IN_N = 12
BUFFER_ZONE = 38
INITIAL_CAPITAL = 10_000_000.0
COST = 0.0004
W_12M, W_6M = 0.60, 0.40
REBAL_DAYS = 14
VARIANT_LABEL = "MR_M_V3_15D"

BASE = "backtest"
FRI_SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"
RUN_DATE = time.strftime("%d%m%Y")

# ── Load prices ───────────────────────────────────────────────────────────────
print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH)
prices["date"] = pd.to_datetime(prices["date"])
open_by_date = {pd.Timestamp(date): grp.set_index("symbol")["open"].to_dict() for date, grp in prices.groupby("date")}
all_trading_days = sorted(open_by_date.keys())
print(f"  {len(all_trading_days)} trading days  ({prices['date'].min().date()} -> {prices['date'].max().date()})")
del prices
gc.collect()

print("Loading benchmark ...")
bench = pd.read_parquet(BENCH_PATH).set_index("date")["close"]
bench.index = pd.DatetimeIndex(bench.index)


# ── Scoring ───────────────────────────────────────────────────────────────────
def compute_mr_scores(signals_df, w_12m, w_6m):
    df = signals_df[signals_df["in_universe"]].copy()
    bad = df["vol_252"].isna() | (df["vol_252"] == 0) | df["ret_12m1m"].isna() | df["ret_6m1m"].isna()
    df = df[~bad].copy()
    if len(df) < 10:
        return pd.DataFrame()
    df["mr_12"] = df["ret_12m1m"] / df["vol_252"]
    df["mr_6"] = df["ret_6m1m"] / df["vol_252"]
    df["z_12"] = (df["mr_12"] - df["mr_12"].mean()) / df["mr_12"].std(ddof=1)
    df["z_6"] = (df["mr_6"] - df["mr_6"].mean()) / df["mr_6"].std(ddof=1)
    df["weighted_z"] = w_12m * df["z_12"] + w_6m * df["z_6"]
    df["norm_momentum_score"] = df["weighted_z"].apply(lambda wz: 1 + wz if wz >= 0 else 1.0 / (1.0 - wz))
    df["mr_rank"] = df["norm_momentum_score"].rank(method="min", ascending=False).astype("Int64")
    return df.sort_values("mr_rank").reset_index(drop=True)


# ── Reconstitution ────────────────────────────────────────────────────────────
def reconstitute(ranked_df, current_holdings):
    if ranked_df.empty:
        return set(), {}

    all_scored = set(ranked_df["symbol"])
    rank_lookup = dict(zip(ranked_df["symbol"], ranked_df["mr_rank"].astype(int), strict=False))
    score_lookup = dict(zip(ranked_df["symbol"], ranked_df["norm_momentum_score"], strict=False))
    unscored_holdings = current_holdings - all_scored

    portfolio = {s for s in current_holdings if s in all_scored and rank_lookup[s] <= BUFFER_ZONE}
    forced_out = (current_holdings - portfolio) | unscored_holdings

    forced_in_candidates = ranked_df[
        (ranked_df["mr_rank"] <= FORCED_IN_N) & (~ranked_df["symbol"].isin(current_holdings))
    ].sort_values("mr_rank")

    for _, row in forced_in_candidates.iterrows():
        new_stock = row["symbol"]
        holdings_in_port = portfolio & current_holdings
        if holdings_in_port:
            weakest = min(holdings_in_port, key=lambda s: score_lookup.get(s, 0))
            portfolio.discard(weakest)
            forced_out.add(weakest)
        portfolio.add(new_stock)

    slots_remaining = PORTFOLIO_N - len(portfolio)
    if slots_remaining > 0:
        fill_pool = ranked_df[
            ~ranked_df["symbol"].isin(portfolio) & ~ranked_df["symbol"].isin(current_holdings)
        ].sort_values("mr_rank")
        for _, row in fill_pool.iterrows():
            if slots_remaining == 0:
                break
            portfolio.add(row["symbol"])
            slots_remaining -= 1

    action_map = {}
    for s in portfolio:
        action_map[s] = "HOLD" if s in current_holdings else "BUY"
    for s in forced_out:
        if s not in portfolio:
            action_map[s] = "SELL"
    for s in all_scored:
        if s not in action_map and rank_lookup[s] <= BUFFER_ZONE:
            action_map[s] = "WATCHLIST"

    return portfolio, action_map


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_date(fname):
    d = fname.replace("signals_", "").replace(".parquet", "")
    return pd.Timestamp(f"{d[4:8]}-{d[2:4]}-{d[0:2]}")


def next_trading_day(dt):
    for td in all_trading_days:
        if td > dt:
            return td
    return None


def to_biweekly_pairs(pairs, min_days=15):
    """
    Select signal/exec pairs where each exec_date is at least
    min_days after the previous selected exec_date.
    Gives a clean ~15-day rebalance cadence from the existing
    weekly Friday signal files.
    """
    selected = []
    last_exec = None
    for sig_date, exec_date, path in sorted(pairs, key=lambda x: x[1]):
        if last_exec is None or (exec_date - last_exec).days >= min_days:
            selected.append((sig_date, exec_date, path))
            last_exec = exec_date
    return selected


# ── Build bi-weekly pairs ─────────────────────────────────────────────────────
print("Building bi-weekly (~15d) pairs ...")
fri_files = sorted(
    f
    for f in os.listdir(FRI_SIG_DIR)
    if f.startswith("signals_") and f.endswith(".parquet") and os.path.isfile(os.path.join(FRI_SIG_DIR, f))
)
all_pairs = []
for fname in fri_files:
    try:
        sig_date = parse_date(fname)
        exec_date = next_trading_day(sig_date)
        if exec_date and open_by_date.get(exec_date):
            all_pairs.append((sig_date, exec_date, os.path.join(FRI_SIG_DIR, fname)))
    except:
        continue
all_pairs.sort(key=lambda x: x[1])
biweekly_pairs = to_biweekly_pairs(all_pairs, min_days=REBAL_DAYS)
print(f"  {len(biweekly_pairs)} rebalance periods  ({biweekly_pairs[0][1].date()} -> {biweekly_pairs[-1][1].date()})")

# ── Run backtest ──────────────────────────────────────────────────────────────
print(f"\nRunning {VARIANT_LABEL} (W_12M={W_12M}, W_6M={W_6M}, REBAL={REBAL_DAYS}d) ...")
state = PortfolioState(initial_capital=INITIAL_CAPITAL)
nav_path = []
all_activity = []
t0 = time.time()

for i, (sig_date, exec_date, sig_path) in enumerate(biweekly_pairs):
    signals = pd.read_parquet(sig_path)
    exec_px = open_by_date[exec_date]
    ranked_df = compute_mr_scores(signals, W_12M, W_6M)
    current_holdings = set(state.holdings.keys())
    top25_symbols, action_map = reconstitute(ranked_df, current_holdings)

    port_value_post, port_value_pre, activity = state.rebalance(list(top25_symbols), exec_px, exec_date, VARIANT_LABEL)

    mr_meta = {}
    if not ranked_df.empty:
        for _, row in ranked_df.iterrows():
            mr_meta[row["symbol"]] = {
                "mr_rank": row["mr_rank"],
                "norm_momentum_score": row["norm_momentum_score"],
                "weighted_z": row["weighted_z"],
            }

    for row in activity:
        sym = row["symbol"]
        row["signal_date"] = sig_date
        row["mr_action"] = action_map.get(sym, row["action"])
        meta = mr_meta.get(sym, {})
        row["mr_rank"] = meta.get("mr_rank", np.nan)
        row["norm_momentum_score"] = meta.get("norm_momentum_score", np.nan)
        row["weighted_z"] = meta.get("weighted_z", np.nan)

    nav_path.append((sig_date, exec_date, port_value_pre, port_value_post))
    all_activity.extend(activity)

    if (i + 1) % 20 == 0 or i == 0 or (i + 1) == len(biweekly_pairs):
        elapsed = time.time() - t0
        remaining = elapsed / (i + 1) * (len(biweekly_pairs) - i - 1)
        print(
            f"  [{i + 1:03d}/{len(biweekly_pairs)}] "
            f"sig={sig_date.date()} exec={exec_date.date()} "
            f"NAV=Rs{port_value_post / 1e6:.3f}M | "
            f"{elapsed:.0f}s elapsed {remaining:.0f}s ETA",
            flush=True,
        )
    gc.collect()

# ── NAV series ────────────────────────────────────────────────────────────────
exec_dates = [d for _, d, _, _ in nav_path]
navs = [v for _, _, _, v in nav_path]
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

returns_df = pd.DataFrame(
    {
        "signal_friday": [d for d, _, _, _ in nav_path],
        "exec_date": pd.to_datetime(exec_dates),
        "nav": navs,
        "period_ret": wrets,
        "cum_ret": cum_ret.values,
        "benchmark_ret": bm_ret.values,
    }
)
activity_df = pd.DataFrame(all_activity)

# ── Gross metrics ─────────────────────────────────────────────────────────────
rets = returns_df["period_ret"].iloc[1:].dropna()
days = (returns_df["exec_date"].iloc[-1] - returns_df["exec_date"].iloc[0]).days
ny = days / 365.25
periods_py = len(rets) / ny
cagr_gross = (navs[-1] / navs[0]) ** (1 / ny) - 1
sharpe_gross = rets.mean() / rets.std() * np.sqrt(periods_py)
running_max = pd.Series(navs).cummax()
max_dd = ((pd.Series(navs) - running_max) / running_max).min()
worst = rets.min()
tail = rets.nsmallest(max(1, int(len(rets) * 0.10))).mean()

print(f"\n{'=' * 60}")
print(f"GROSS RESULTS: {VARIANT_LABEL}")
print(f"{'=' * 60}")
print(f"  Rebal cadence : every ~{REBAL_DAYS} calendar days")
print(f"  Periods       : {len(biweekly_pairs)} rebalances over {ny:.1f} years")
print(f"  CAGR          : {cagr_gross * 100:.2f}%")
print(f"  Sharpe        : {sharpe_gross:.3f}")
print(f"  Max DD        : {max_dd * 100:.2f}%")
print(f"  Worst period  : {worst * 100:.2f}%")
print(f"  Mean tail     : {tail * 100:.2f}%")
print(f"{'=' * 60}")
print("  vs V3 Monthly (gross benchmark): CAGR 34.12% | Sharpe 1.197 | MaxDD -35.08%")
print(f"  CAGR delta    : {(cagr_gross * 100 - 34.12):+.2f}%")
print(f"{'=' * 60}")

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs(RESULTS_DIR, exist_ok=True)
wr_path = f"{RESULTS_DIR}/{VARIANT_LABEL}_returns_{RUN_DATE}.csv"
act_path = f"{RESULTS_DIR}/{VARIANT_LABEL}_activity_{RUN_DATE}.csv"
returns_df.to_csv(wr_path, index=False)
activity_df.to_csv(act_path, index=False)
print(f"\n  Saved: {wr_path}")
print(f"  Saved: {act_path}")
print(f"  Time : {(time.time() - t0) / 60:.1f} min")
