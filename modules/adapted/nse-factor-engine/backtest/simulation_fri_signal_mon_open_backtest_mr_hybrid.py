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
MR Hybrid Backtest — Weinstein as reconstitution filter, not a gate

MR_HYB   : full universe scored, Weinstein applied in reconstitution, weekly
MR_HYB_M : full universe scored, Weinstein applied in reconstitution, monthly

Hybrid reconstitution rules:
  - Top 12 forced-in (rank 1-12 non-holders): enter regardless of Weinstein
  - Retained holdings (rank <= BUFFER_ZONE): must pass Weinstein, else forced_out
  - Fill slots (rank 13-38 non-holders): must pass Weinstein

Compare against: MR, MR_W, MR_LO, MR_M, MR_W_M, MR_LO_M
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

PORTFOLIO_N = 25
BUFFER_ZONE = 38
FORCED_IN_N = 12
INITIAL_CAPITAL = 10_000_000.0
N_WEEKS_LIMIT = 600

G6_EXCLUDED_LOTTERY = {"LOTTERY", "BORDER_LOTTERY", "EXTREME_LOTTERY", "EXTREME LOTTERY"}

BASE = "/home/ec2-user/nse-factor-engine/backtest"
FRI_SIG_DIR = f"{BASE}/signals/historical"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"
BENCH_PATH = f"{BASE}/data/benchmark/nifty500_weekly.parquet"
RESULTS_DIR = f"{BASE}/results"
RUN_DATE = time.strftime("%d%m%Y")

os.makedirs(RESULTS_DIR, exist_ok=True)

# All 8 variants — 6 from before + 2 new hybrid
VARIANTS = [
    (0, False, False, "MR", "No gate | B38 | Weekly"),
    (2, False, False, "MR_W", "Weinstein gate | B38 | Weekly"),
    (7, False, False, "MR_LO", "Lottery excl | B38 | Weekly"),
    (0, False, True, "MR_M", "No gate | B38 | Monthly"),
    (2, False, True, "MR_W_M", "Weinstein gate | B38 | Monthly"),
    (7, False, True, "MR_LO_M", "Lottery excl | B38 | Monthly"),
    (0, True, False, "MR_HYB", "Hybrid Weinstein | B38 | Weekly"),
    (0, True, True, "MR_HYB_M", "Hybrid Weinstein | B38 | Monthly"),
]


# ── Gate (pre-scoring filter) ──────────────────────────────────────────────────
def apply_gate(df, gate_id):
    if gate_id == 0:
        return df
    elif gate_id == 2:
        return df[df["weinstein_stage2"]].copy()
    elif gate_id == 7:
        return df[~df["lottery_class"].isin(G6_EXCLUDED_LOTTERY)].copy()
    return df


# ── MR scoring ─────────────────────────────────────────────────────────────────
def compute_mr_scores(signals_df, gate_id):
    df = signals_df[signals_df["in_universe"]].copy()
    df = apply_gate(df, gate_id)

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


# ── Standard reconstitution (corrected v2) ────────────────────────────────────
# Step 3: Holdings rank > 38 → removed.
# Step 4: Non-holders rank <= 12 → forced in, each displaces lowest scoring holding.
# Step 5: Remaining holdings rank <= 38 → retained.
# Step 6: Fill remaining slots with non-holders by rank until count = 25.
def reconstitute(ranked_df, current_holdings):
    if ranked_df.empty:
        return set(), {}

    all_scored = set(ranked_df["symbol"])
    rank_lookup = dict(zip(ranked_df["symbol"], ranked_df["mr_rank"].astype(int), strict=False))
    score_lookup = dict(zip(ranked_df["symbol"], ranked_df["norm_momentum_score"], strict=False))
    unscored_holdings = current_holdings - all_scored

    # Step 3: Remove holdings ranked > 38 or unscored
    portfolio = {s for s in current_holdings if s in all_scored and rank_lookup[s] <= BUFFER_ZONE}
    forced_out = (current_holdings - portfolio) | unscored_holdings

    # Step 4: Non-holders in ranks 1-12 → forced in
    # Each one displaces the lowest momentum score holding in current portfolio
    forced_in_candidates = ranked_df[
        (ranked_df["mr_rank"] <= FORCED_IN_N) & (~ranked_df["symbol"].isin(current_holdings))
    ].sort_values("mr_rank")

    for _, row in forced_in_candidates.iterrows():
        new_stock = row["symbol"]
        # Always displace the lowest scoring holding — unconditional
        holdings_in_port = portfolio & current_holdings
        if holdings_in_port:
            weakest = min(holdings_in_port, key=lambda s: score_lookup.get(s, 0))
            portfolio.discard(weakest)
            forced_out.add(weakest)
        portfolio.add(new_stock)

    # Step 5: Remaining holdings rank <= 38 already in portfolio — nothing to do,
    # they survived Step 3 and were not displaced in Step 4.

    # Step 6: Fill remaining slots with non-holders by rank
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

    top25_symbols = portfolio

    # Action map
    action_map = {}
    for s in top25_symbols:
        action_map[s] = "HOLD" if s in current_holdings else "BUY"
    for s in forced_out:
        if s not in top25_symbols:
            action_map[s] = "SELL"
    for s in all_scored:
        if s not in action_map and rank_lookup[s] <= BUFFER_ZONE:
            action_map[s] = "WATCHLIST"

    return top25_symbols, action_map


# ── Hybrid reconstitution (corrected v2) ──────────────────────────────────────
SET2_TARGET = PORTFOLIO_N - FORCED_IN_N  # 13


def reconstitute_hybrid(ranked_df, current_holdings):
    """
    SET 1 (12): top FORCED_IN_N=12 overall by mr_rank. WS2 bypassed.
    SET 2 pool: mr_rank 13-38 by ORIGINAL rank, THEN drop WS2=False. No re-ranking.
    SET 2 selection (13 slots): HOLDs first (by mr_rank asc), fill with non-holders (by mr_rank asc).
    WS2 failures (ranks 13-38): holdings -> SELL, non-holders -> excluded.
    """
    if ranked_df.empty:
        return set(), {}

    all_scored = set(ranked_df["symbol"])
    unscored_holdings = current_holdings - all_scored

    # SET 1: top 12 overall, WS2 bypassed
    set1_df = ranked_df[ranked_df["mr_rank"] <= FORCED_IN_N].sort_values("mr_rank").copy()
    set1_symbols = set(set1_df["symbol"])

    # SET 2 pool: clip to original mr_rank 13-38 FIRST, then drop WS2=False
    set2_pool_raw = ranked_df[
        (ranked_df["mr_rank"] > FORCED_IN_N) & (ranked_df["mr_rank"] <= BUFFER_ZONE)
    ].copy()
    ws2_fail_symbols = set(set2_pool_raw[not set2_pool_raw["weinstein_stage2"]]["symbol"])
    set2_pool = set2_pool_raw[set2_pool_raw["weinstein_stage2"]].copy()

    # SET 2 selection: HOLDs first by mr_rank, fill remaining with non-holders by mr_rank
    set2_holds = set2_pool[set2_pool["symbol"].isin(current_holdings)].sort_values("mr_rank")
    set2_nonholders = set2_pool[~set2_pool["symbol"].isin(current_holdings)].sort_values("mr_rank")

    holds_selected = set(set2_holds.head(SET2_TARGET)["symbol"])
    slots_remaining = SET2_TARGET - len(holds_selected)
    fill_selected = (
        set(set2_nonholders.head(slots_remaining)["symbol"]) if slots_remaining > 0 else set()
    )

    set2_selected = holds_selected | fill_selected
    watchlist_pool = set(set2_pool["symbol"]) - set2_selected

    top25_symbols = set1_symbols | set2_selected
    if len(top25_symbols) != PORTFOLIO_N:
        print(
            f"  WARNING: portfolio={len(top25_symbols)}, expected {PORTFOLIO_N} "
            f"(WS2 coverage thin in ranks 13-{BUFFER_ZONE})"
        )

    # Action map
    ws2_forced_sells = ws2_fail_symbols & current_holdings
    action_map = {}
    for s in top25_symbols:
        action_map[s] = "HOLD" if s in current_holdings else "BUY"
    for s in ws2_forced_sells:
        if s not in top25_symbols:
            action_map[s] = "SELL"
    for s in unscored_holdings:
        action_map[s] = "SELL"
    for s in watchlist_pool:
        if s not in action_map:
            action_map[s] = "WATCHLIST"

    return top25_symbols, action_map


# ── Monthly pair filter ────────────────────────────────────────────────────────
def to_monthly_pairs(pairs):
    monthly = {}
    for sig_date, exec_date, path in pairs:
        key = (exec_date.year, exec_date.month)
        monthly[key] = (sig_date, exec_date, path)
    return sorted(monthly.values(), key=lambda x: x[1])


# ── Performance metrics ────────────────────────────────────────────────────────
def compute_metrics(weekly_df, activity_df, prefix, desc):
    rets = weekly_df["weekly_ret"].iloc[1:].dropna()
    navs = weekly_df["nav"]

    cum = (1 + rets).prod() - 1
    days = (weekly_df["exec_date"].iloc[-1] - weekly_df["exec_date"].iloc[0]).days
    ny = days / 365.25
    cagr = (1 + cum) ** (1 / ny) - 1 if ny > 0 else np.nan

    n_periods = len(rets)
    periods_py = n_periods / ny if ny > 0 else 52
    rf_period = (1 + 0.07) ** (1 / periods_py) - 1
    excess = rets - rf_period
    sharpe = (excess.mean() / excess.std()) * np.sqrt(periods_py) if excess.std() > 0 else np.nan

    running_max = navs.cummax()
    drawdown = (navs - running_max) / running_max
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan
    hit_rate = (rets > 0).sum() / len(rets)

    bm_rets = weekly_df["benchmark_ret"].iloc[1:].dropna()
    bm_cum = (1 + bm_rets).prod() - 1
    bm_cagr = (1 + bm_cum) ** (1 / ny) - 1 if ny > 0 else np.nan

    turnover_list = []
    for _, grp in activity_df.groupby("signal_date"):
        n_buy = (grp["action"] == "BUY").sum()
        n_total = grp["symbol"].nunique()
        if n_total > 0:
            turnover_list.append(n_buy / n_total)
    avg_turnover = np.mean(turnover_list) if turnover_list else np.nan

    return {
        "Variant": prefix,
        "Description": desc,
        "CAGR": cagr,
        "BM CAGR": bm_cagr,
        "Alpha": cagr - bm_cagr,
        "Sharpe": sharpe,
        "Calmar": calmar,
        "Max DD": max_dd,
        "Hit Rate": hit_rate,
        "Avg Turnover": avg_turnover,
        "NAV end (M)": navs.iloc[-1] / 1e6,
        "Periods": n_periods,
    }


# ── Load prices & benchmark ────────────────────────────────────────────────────
print("=" * 75)
print("MR HYBRID BACKTEST — 8 VARIANTS")
print(f"Run date: {RUN_DATE}")
print("=" * 75)

print("\nLoading prices ...")
prices = pd.read_parquet(PRICES_PATH)
open_by_date = {
    pd.Timestamp(date): grp.set_index("symbol")["open"].to_dict()
    for date, grp in prices.groupby("date")
}
all_trading_days = sorted(open_by_date.keys())
print(
    f"  trading days: {len(all_trading_days)}  "
    f"({prices['date'].min().date()} -> {prices['date'].max().date()})"
)
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


print("Building pairs ...")
fri_files = sorted(
    f
    for f in os.listdir(FRI_SIG_DIR)
    if f.startswith("signals_")
    and f.endswith(".parquet")
    and os.path.isfile(os.path.join(FRI_SIG_DIR, f))
)
all_pairs = []
for fname in fri_files:
    sig_date = parse_date(fname)
    exec_date = next_trading_day(sig_date)
    if exec_date and open_by_date.get(exec_date):
        all_pairs.append((sig_date, exec_date, os.path.join(FRI_SIG_DIR, fname)))
all_pairs.sort(key=lambda x: x[1])
all_pairs = all_pairs[:N_WEEKS_LIMIT]

weekly_pairs = all_pairs
monthly_pairs = to_monthly_pairs(all_pairs)
print(f"  weekly: {len(weekly_pairs)}  monthly: {len(monthly_pairs)}")


# ── Run each variant ───────────────────────────────────────────────────────────
all_metrics = []

for gate_id, is_hybrid, is_monthly, prefix, desc in VARIANTS:
    print(f"\n{'=' * 75}")
    print(f"VARIANT: {prefix}  |  {desc}")
    print(f"{'=' * 75}")

    pairs = monthly_pairs if is_monthly else weekly_pairs

    state = PortfolioState(initial_capital=INITIAL_CAPITAL)
    nav_path = []
    all_activity = []
    t0 = time.time()

    for i, (sig_date, exec_date, sig_path) in enumerate(pairs):
        signals = pd.read_parquet(sig_path)
        exec_px = open_by_date[exec_date]

        ranked_df = compute_mr_scores(signals, gate_id)
        current_holdings = set(state.holdings.keys())

        if is_hybrid:
            top25_symbols, action_map = reconstitute_hybrid(ranked_df, current_holdings)
        else:
            top25_symbols, action_map = reconstitute(ranked_df, current_holdings)
        top25 = list(top25_symbols)

        port_value_post, port_value_pre, activity = state.rebalance(
            top25, exec_px, exec_date, prefix
        )

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

        if (i + 1) % 50 == 0 or i == 0 or (i + 1) == len(pairs):
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (len(pairs) - i - 1)
            print(
                f"  [{i + 1:03d}/{len(pairs)}] "
                f"sig={sig_date.date()} exec={exec_date.date()} "
                f"NAV=Rs{port_value_post / 1e6:.3f}M | "
                f"{elapsed:.0f}s elapsed {remaining:.0f}s ETA",
                flush=True,
            )

        gc.collect()

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

    weekly_df = pd.DataFrame(
        {
            "signal_friday": [d for d, _, _, _ in nav_path],
            "exec_date": pd.to_datetime(exec_dates),
            "nav": navs,
            "weekly_ret": wrets,
            "cum_ret": cum_ret.values,
            "benchmark_ret": bm_ret.values,
        }
    )
    activity_df = pd.DataFrame(all_activity)

    wr_path = f"{RESULTS_DIR}/{prefix}_weekly_returns_{RUN_DATE}.csv"
    act_path = f"{RESULTS_DIR}/{prefix}_activity_{RUN_DATE}.csv"
    weekly_df.to_csv(wr_path, index=False)
    activity_df.to_csv(act_path, index=False)
    print(f"  -> {wr_path}")
    print(f"  -> {act_path}")

    metrics = compute_metrics(weekly_df, activity_df, prefix, desc)
    all_metrics.append(metrics)

    elapsed_total = time.time() - t0
    print(
        f"  CAGR={metrics['CAGR']:.2%}  Sharpe={metrics['Sharpe']:.3f}  "
        f"MaxDD={metrics['Max DD']:.2%}  Alpha={metrics['Alpha']:.2%}  "
        f"Periods={metrics['Periods']}  Time={elapsed_total / 60:.1f}min"
    )


# ── Combined summary ───────────────────────────────────────────────────────────
summary = pd.DataFrame(all_metrics)
summary_path = f"{RESULTS_DIR}/hybrid_summary_{RUN_DATE}.csv"
summary.to_csv(summary_path, index=False)

sorted_metrics = sorted(all_metrics, key=lambda x: x["NAV end (M)"], reverse=True)

print("\n" + "=" * 100)
print("COMBINED PERFORMANCE SUMMARY — sorted by NAV descending")
print("=" * 100)
print(
    "%-13s %-32s %7s %7s %7s %7s %7s %6s %7s %9s %4s"
    % (
        "Variant",
        "Description",
        "CAGR",
        "Alpha",
        "Sharpe",
        "Calmar",
        "MaxDD",
        "Hit%",
        "Turn%",
        "NAV(M)",
        "N",
    )
)
print("-" * 100)
for r in sorted_metrics:
    print(
        "%-13s %-32s %6.2f%% %6.2f%% %7.3f %7.3f %6.2f%% %5.1f%% %6.1f%% Rs%6.3fM %4d"
        % (
            r["Variant"],
            r["Description"],
            r["CAGR"] * 100,
            r["Alpha"] * 100,
            r["Sharpe"],
            r["Calmar"],
            r["Max DD"] * 100,
            r["Hit Rate"] * 100,
            r["Avg Turnover"] * 100,
            r["NAV end (M)"],
            r["Periods"],
        )
    )
print("\nSummary CSV -> " + summary_path)
print("=" * 100)
