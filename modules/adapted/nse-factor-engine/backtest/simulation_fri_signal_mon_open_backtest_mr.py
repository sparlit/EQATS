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
Friday Signal -> Monday Open Execution — MR Scoring Backtest

Signal date  : Friday close (backtest/signals/historical/, 511 files)
Execute date : next trading day after signal Friday (Monday, or Tuesday if holiday)
NAV          : tracked at Monday open prices (same convention as G6_C6 backtest)

Scoring      : Momentum Ratio (MR) methodology
  MR12 = ret_12m1m / vol_252
  MR6  = ret_6m1m  / vol_252
  Z12, Z6 cross-sectional, Weighted_Z = 50/50, Normalized_Momentum_Score

Reconstitution (buffer zone, applied each week):
  PORTFOLIO_N  = 25
  BUFFER_ZONE  = 38   (holdings with rank <= 38 are retained)
  FORCED_IN_N  = 12   (top 12 non-holders always enter)

USE_G6_GATE flag:
  0 -> score all in_universe stocks (no gate)    output prefix: MR
  1 -> apply G6 gate before scoring              output prefix: MR_G6

Outputs (in backtest/results/):
  {PREFIX}_weekly_returns_{RUN_DATE}.csv
    columns: signal_friday, exec_date, nav, weekly_ret, cum_ret, benchmark_ret
  {PREFIX}_activity_{RUN_DATE}.csv
    full per-symbol BUY/SELL/HOLD/WATCHLIST activity log, all weeks

Portfolio mechanics: reuses backtest/simulation/portfolio.py unchanged.
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

# ── Configuration ─────────────────────────────────────────────────────────────

USE_G6_GATE = 2
USE_ADTV_FILTER = True

PORTFOLIO_N = 25
BUFFER_ZONE = 38
FORCED_IN_N = 12
INITIAL_CAPITAL = 10_000_000.0
N_WEEKS_LIMIT = 600  # >= 511 runs full history; lower for quick test

G6_EXCLUDED_LOTTERY = {"LOTTERY", "BORDER_LOTTERY", "EXTREME_LOTTERY"}

BASE = "/home/ec2-user/nse-factor-engine/backtest"
FRI_SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"

gate_sfx = "_G6" if USE_G6_GATE == 1 else ("_W" if USE_G6_GATE == 2 else "")
adtv_sfx = "_ADTV" if USE_ADTV_FILTER else ""
PREFIX = f"MR{gate_sfx}{adtv_sfx}"
RUN_DATE = time.strftime("%d%m%Y")

os.makedirs(RESULTS_DIR, exist_ok=True)

# ── MR Scoring ────────────────────────────────────────────────────────────────


def _apply_g6_gate(df):
    global USE_G6_GATE
    if USE_G6_GATE == 2:
        out = df[df["weinstein_stage2"]].copy()
        print(f"Weinstein-only gate: {len(df)} -> {len(out)} pass ({len(df) - len(out)} dropped)")
        return out
    return df[
        (df["weinstein_stage2"])
        & (~df["lottery_class"].isin(G6_EXCLUDED_LOTTERY))
        & (df["rs_excess_ret_mkt"] > 0)
    ].copy()


def compute_mr_scores(signals_df):
    """
    Given one Friday's signals dataframe, returns a full ranked dataframe
    (all scoreable in-universe stocks) sorted by mr_rank ascending.
    Returns empty DataFrame if too few valid rows.
    """
    df = signals_df[signals_df["in_universe"]].copy()

    if USE_G6_GATE in (1, 2):
        df = _apply_g6_gate(df)

    # ADTV bottom 10 percentile filter
    if USE_ADTV_FILTER:
        adtv_p10 = df["adtv_63_cr"].quantile(0.10)
        before = len(df)
        df = df[df["adtv_63_cr"] > adtv_p10].copy()
        print(f"ADTV filter (p10=Rs{adtv_p10:.2f}Cr): {before} -> {len(df)}")

    # Drop rows missing any scoring input
    bad = (
        df["vol_252"].isna() | (df["vol_252"] == 0) | df["ret_12m1m"].isna() | df["ret_6m1m"].isna()
    )
    df = df[~bad].copy()

    if len(df) < 10:
        return pd.DataFrame()

    df["mr_12"] = df["ret_12m1m"] / df["vol_252"]
    df["mr_6"] = df["ret_6m1m"] / df["vol_252"]

    df["z_12"] = (df["mr_12"] - df["mr_12"].mean()) / df["mr_12"].std(ddof=1)
    df["z_6"] = (df["mr_6"] - df["mr_6"].mean()) / df["mr_6"].std(ddof=1)

    df["weighted_z"] = 0.5 * df["z_12"] + 0.5 * df["z_6"]

    df["norm_momentum_score"] = df["weighted_z"].apply(
        lambda wz: 1 + wz if wz >= 0 else 1.0 / (1.0 - wz)
    )

    df["mr_rank"] = df["norm_momentum_score"].rank(method="min", ascending=False).astype("Int64")

    return df.sort_values("mr_rank").reset_index(drop=True)


def reconstitute(ranked_df, current_holdings):
    """
    Applies buffer zone reconstitution to derive final TOP_25 symbols.

    Returns:
        top25_symbols : set of 25 symbols
        action_map    : {symbol: action_string} for activity log
    """
    if ranked_df.empty:
        return set(), {}

    all_scored = set(ranked_df["symbol"])
    rank_lookup = dict(zip(ranked_df["symbol"], ranked_df["mr_rank"].astype(int), strict=False))

    # Holdings that didn't survive scoring (NaN inputs) — force out
    unscored_holdings = current_holdings - all_scored

    scoreable_holdings = current_holdings & all_scored

    # Split scoreable holdings
    retained = {s for s in scoreable_holdings if rank_lookup[s] <= BUFFER_ZONE}
    forced_out = {s for s in scoreable_holdings if rank_lookup[s] > BUFFER_ZONE}
    forced_out |= unscored_holdings  # unscored holdings also exit

    # Top FORCED_IN_N non-holders
    non_holders_ranked = ranked_df[~ranked_df["symbol"].isin(scoreable_holdings)].sort_values(
        "mr_rank"
    )
    forced_in = set(non_holders_ranked.head(FORCED_IN_N)["symbol"])

    # Edge case: retained + forced_in > PORTFOLIO_N
    # Drop lowest-ranked retained first
    combined = retained | forced_in
    if len(combined) > PORTFOLIO_N:
        excess = len(combined) - PORTFOLIO_N
        retained_sorted = sorted(retained, key=lambda s: rank_lookup[s], reverse=True)
        drop = set(retained_sorted[:excess])
        forced_out |= drop
        retained -= drop

    # Fill remaining slots from non-holders not already in forced_in
    slots_filled = retained | forced_in
    slots_remaining = PORTFOLIO_N - len(slots_filled)

    if slots_remaining > 0:
        fill_pool = ranked_df[
            ~ranked_df["symbol"].isin(slots_filled) & ~ranked_df["symbol"].isin(scoreable_holdings)
        ].sort_values("mr_rank")
        fill_symbols = set(fill_pool.head(slots_remaining)["symbol"])
    else:
        fill_symbols = set()

    top25_symbols = retained | forced_in | fill_symbols

    # Safety check — degrade gracefully if universe too small
    if len(top25_symbols) < PORTFOLIO_N:
        pass  # PortfolioState handles partial portfolios fine

    # Build action map for activity enrichment
    action_map = {}
    for s in top25_symbols:
        action_map[s] = "HOLD" if s in current_holdings else "BUY"
    for s in forced_out:
        if s not in top25_symbols:
            action_map[s] = "SELL"
    # WATCHLIST: rank <= BUFFER_ZONE, not a holder, not in TOP_25
    for s in all_scored:
        if s not in action_map and rank_lookup[s] <= BUFFER_ZONE:
            action_map[s] = "WATCHLIST"

    return top25_symbols, action_map


# ── Load prices & benchmark ───────────────────────────────────────────────────

print(f"{'=' * 65}")
print(f"MR SCORING BACKTEST  |  USE_G6_GATE={USE_G6_GATE}  |  PREFIX={PREFIX}")
print(f"BUFFER_ZONE={BUFFER_ZONE}  FORCED_IN_N={FORCED_IN_N}  PORTFOLIO_N={PORTFOLIO_N}")
print(f"{'=' * 65}")

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


def parse_date(fname):
    d = fname.replace("signals_", "").replace(".parquet", "")
    return pd.Timestamp(f"{d[4:8]}-{d[2:4]}-{d[0:2]}")


# ── Build Friday -> Monday pairs ──────────────────────────────────────────────

print("Building Friday-signal -> Monday-open week pairs ...")
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
print(f"  first : sig={mon_pairs[0][0].date()} exec={mon_pairs[0][1].date()}")
print(f"  last  : sig={mon_pairs[-1][0].date()} exec={mon_pairs[-1][1].date()}")

# ── Main backtest loop ────────────────────────────────────────────────────────

print(f"\n{'=' * 65}")
print(f"RUNNING: {PREFIX}  ({len(mon_pairs)} weeks)")
print(f"{'=' * 65}")

state = PortfolioState(initial_capital=INITIAL_CAPITAL)
nav_path = []
all_activity = []
t0 = time.time()

for i, (sig_date, exec_date, sig_path) in enumerate(mon_pairs):
    signals = pd.read_parquet(sig_path)
    exec_px = open_by_date[exec_date]

    # Score this Friday's universe
    ranked_df = compute_mr_scores(signals)

    # Derive top25 via buffer zone reconstitution
    current_holdings = set(state.holdings.keys())
    top25_symbols, action_map = reconstitute(ranked_df, current_holdings)
    top25 = list(top25_symbols)

    # Rebalance (portfolio.py unchanged)
    port_value_post, port_value_pre, activity = state.rebalance(top25, exec_px, exec_date, PREFIX)

    # Enrich activity with MR scoring metadata
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
        if sym in mr_meta:
            row["mr_rank"] = mr_meta[sym]["mr_rank"]
            row["norm_momentum_score"] = mr_meta[sym]["norm_momentum_score"]
            row["weighted_z"] = mr_meta[sym]["weighted_z"]
        else:
            row["mr_rank"] = np.nan
            row["norm_momentum_score"] = np.nan
            row["weighted_z"] = np.nan

    nav_path.append((sig_date, exec_date, port_value_pre, port_value_post))
    all_activity.extend(activity)

    if (i + 1) % 50 == 0 or i == 0 or (i + 1) == len(mon_pairs):
        elapsed = time.time() - t0
        remaining = elapsed / (i + 1) * (len(mon_pairs) - i - 1) if i else 0
        print(
            f"  [{i + 1:03d}/{len(mon_pairs)}] "
            f"sig={sig_date.date()} exec={exec_date.date()} "
            f"NAV=Rs{port_value_post / 1e6:.3f}M | "
            f"{elapsed:.0f}s elapsed {remaining:.0f}s ETA",
            flush=True,
        )

    gc.collect()

# ── Weekly returns & benchmark ────────────────────────────────────────────────

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

# ── Write outputs ─────────────────────────────────────────────────────────────

wr_path = f"{RESULTS_DIR}/{PREFIX}_weekly_returns_{RUN_DATE}.csv"
act_path = f"{RESULTS_DIR}/{PREFIX}_activity_{RUN_DATE}.csv"
weekly_df.to_csv(wr_path, index=False)
activity_df.to_csv(act_path, index=False)

print(f"\n  weekly_returns -> {wr_path}  ({os.path.getsize(wr_path) / 1024:.0f} KB)")
print(f"  activity_log   -> {act_path}  ({os.path.getsize(act_path) / 1024 / 1024:.2f} MB)")

# ── Performance summary ───────────────────────────────────────────────────────

rets = weekly_df["weekly_ret"].iloc[1:].dropna()
cum = (1 + rets).prod() - 1
ny = len(rets) / 52
cagr = (1 + cum) ** (1 / ny) - 1 if ny > 0 else np.nan

rf_weekly = (1 + 0.07) ** (1 / 52) - 1
excess_ret = rets - rf_weekly
sharpe = (excess_ret.mean() / excess_ret.std()) * np.sqrt(52) if excess_ret.std() > 0 else np.nan

nav_series = weekly_df["nav"]
running_max = nav_series.cummax()
drawdown = (nav_series - running_max) / running_max
max_dd = drawdown.min()

turnover_list = []
for sig_date, grp in activity_df.groupby("signal_date"):
    n_buy = (grp["action"] == "BUY").sum()
    n_total = grp["symbol"].nunique()
    if n_total > 0:
        turnover_list.append(n_buy / n_total)
avg_turnover = np.mean(turnover_list) if turnover_list else np.nan

print(f"\n{'=' * 65}")
print(f"PERFORMANCE SUMMARY [{PREFIX}]")
print(f"{'=' * 65}")
print(f"  weeks            : {len(rets)}")
print(f"  full-period CAGR : {cagr:.2%}")
print(f"  Sharpe (RF=7%)   : {sharpe:.3f}")
print(f"  Max Drawdown     : {max_dd:.2%}")
print(f"  Avg Turnover     : {avg_turnover:.2%}")
print(f"  NAV start        : Rs{navs[0] / 1e6:.4f}M")
print(f"  NAV end          : Rs{navs[-1] / 1e6:.3f}M")
print(f"  activity rows    : {len(activity_df)}")
print(f"  total time       : {(time.time() - t0) / 60:.1f} min")
print(f"{'=' * 65}")
