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
MR Scoring Backtest — Gate Variants Comparison

Runs 5 gate variants sequentially in one process and prints a combined
performance summary table at the end.

Gate variants (USE_G6_GATE):
  0 : MR      — no gate, all in_universe
  1 : MR_G6   — full G6 (weinstein + lottery + alpha)
  2 : MR_W    — weinstein_stage2 only
  3 : MR_WA   — weinstein_stage2 AND alpha > 0
  4 : MR_LA   — lottery_class not excluded AND alpha > 0

Column notes (historical signal files):
  alpha proxy  : rs_excess_ret_mkt  (alpha_12m1m_ew absent in historical files)
                 falls back to alpha_12m1m_ew if present (future-proof)
  lottery_class: historical uses 'EXTREME LOTTERY' (space), production uses
                 'EXTREME_LOTTERY' (underscore) — both handled

Signal cadence : Friday close -> Monday open execution
Portfolio      : PORTFOLIO_N=25, BUFFER_ZONE=38, FORCED_IN_N=12
No ADTV filter (gate comparison in isolation).

Outputs (backtest/results/):
  {PREFIX}_weekly_returns_{DDMMYYYY}.csv
  {PREFIX}_activity_{DDMMYYYY}.csv
  variants_summary_{DDMMYYYY}.csv
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

# ── Configuration ──────────────────────────────────────────────────────────────
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

# ── Variant definitions ────────────────────────────────────────────────────────
VARIANTS = [
    (0, "MR", "No gate — all in_universe"),
    (1, "MR_G6", "Full G6 (weinstein+lottery+alpha)"),
    (2, "MR_W", "Weinstein only"),
    (3, "MR_WA", "Weinstein + alpha > 0"),
    (4, "MR_LA", "Lottery excluded + alpha > 0"),
]


# ── Alpha column resolver ──────────────────────────────────────────────────────
def get_alpha_col(df):
    if "alpha_12m1m_ew" in df.columns:
        return "alpha_12m1m_ew"
    if "rs_excess_ret_mkt" in df.columns:
        return "rs_excess_ret_mkt"
    return None


# ── Gate functions ─────────────────────────────────────────────────────────────
def apply_gate(df, use_g6_gate):
    alpha_col = get_alpha_col(df)

    if use_g6_gate == 0:
        return df

    if use_g6_gate == 1:  # Full G6
        mask = (df["weinstein_stage2"]) & (~df["lottery_class"].isin(G6_EXCLUDED_LOTTERY))
        if alpha_col:
            mask &= df[alpha_col] > 0
        return df[mask].copy()

    if use_g6_gate == 2:  # Weinstein only
        return df[df["weinstein_stage2"]].copy()

    if use_g6_gate == 3:  # Weinstein + alpha (your b)
        mask = df["weinstein_stage2"]
        if alpha_col:
            mask &= df[alpha_col] > 0
        return df[mask].copy()

    if use_g6_gate == 4:  # Lottery excluded + alpha (your c)
        mask = ~df["lottery_class"].isin(G6_EXCLUDED_LOTTERY)
        if alpha_col:
            mask &= df[alpha_col] > 0
        return df[mask].copy()

    return df


# ── MR scoring ─────────────────────────────────────────────────────────────────
def compute_mr_scores(signals_df, use_g6_gate):
    df = signals_df[signals_df["in_universe"]].copy()
    df = apply_gate(df, use_g6_gate)

    bad = df["vol_252"].isna() | (df["vol_252"] == 0) | df["ret_12m1m"].isna() | df["ret_6m1m"].isna()
    df = df[~bad].copy()

    if len(df) < 10:
        return pd.DataFrame()

    df["mr_12"] = df["ret_12m1m"] / df["vol_252"]
    df["mr_6"] = df["ret_6m1m"] / df["vol_252"]

    df["z_12"] = (df["mr_12"] - df["mr_12"].mean()) / df["mr_12"].std(ddof=1)
    df["z_6"] = (df["mr_6"] - df["mr_6"].mean()) / df["mr_6"].std(ddof=1)

    df["weighted_z"] = 0.5 * df["z_12"] + 0.5 * df["z_6"]

    df["norm_momentum_score"] = df["weighted_z"].apply(lambda wz: 1 + wz if wz >= 0 else 1.0 / (1.0 - wz))

    df["mr_rank"] = df["norm_momentum_score"].rank(method="min", ascending=False).astype("Int64")

    return df.sort_values("mr_rank").reset_index(drop=True)


# ── Reconstitution ─────────────────────────────────────────────────────────────
def reconstitute(ranked_df, current_holdings):
    if ranked_df.empty:
        return set(), {}

    all_scored = set(ranked_df["symbol"])
    rank_lookup = dict(zip(ranked_df["symbol"], ranked_df["mr_rank"].astype(int), strict=False))
    unscored_holdings = current_holdings - all_scored
    scoreable = current_holdings & all_scored

    retained = {s for s in scoreable if rank_lookup[s] <= BUFFER_ZONE}
    forced_out = {s for s in scoreable if rank_lookup[s] > BUFFER_ZONE}
    forced_out |= unscored_holdings

    non_holders_ranked = ranked_df[~ranked_df["symbol"].isin(scoreable)].sort_values("mr_rank")
    forced_in = set(non_holders_ranked.head(FORCED_IN_N)["symbol"])

    combined = retained | forced_in
    if len(combined) > PORTFOLIO_N:
        excess = len(combined) - PORTFOLIO_N
        retained_sorted = sorted(retained, key=lambda s: rank_lookup[s], reverse=True)
        drop = set(retained_sorted[:excess])
        forced_out |= drop
        retained -= drop

    slots_filled = retained | forced_in
    slots_remaining = PORTFOLIO_N - len(slots_filled)

    if slots_remaining > 0:
        fill_pool = ranked_df[
            ~ranked_df["symbol"].isin(slots_filled) & ~ranked_df["symbol"].isin(scoreable)
        ].sort_values("mr_rank")
        fill_symbols = set(fill_pool.head(slots_remaining)["symbol"])
    else:
        fill_symbols = set()

    top25_symbols = retained | forced_in | fill_symbols

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


# ── Performance metrics ────────────────────────────────────────────────────────
def compute_metrics(weekly_df, activity_df, prefix, desc):
    rets = weekly_df["weekly_ret"].iloc[1:].dropna()
    navs = weekly_df["nav"]

    cum = (1 + rets).prod() - 1
    ny = len(rets) / 52
    cagr = (1 + cum) ** (1 / ny) - 1 if ny > 0 else np.nan

    rf_weekly = (1 + 0.07) ** (1 / 52) - 1
    excess = rets - rf_weekly
    sharpe = (excess.mean() / excess.std()) * np.sqrt(52) if excess.std() > 0 else np.nan

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

    avg_universe = activity_df.groupby("signal_date")["symbol"].nunique().mean()

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
        "Avg Universe": avg_universe,
        "NAV end (M)": navs.iloc[-1] / 1e6,
        "Weeks": len(rets),
    }


# ── Load prices & benchmark once ───────────────────────────────────────────────
print("=" * 70)
print(f"MR BACKTEST — {len(VARIANTS)} GATE VARIANTS")
print(f"Run date: {RUN_DATE}")
print("=" * 70)

print("\nLoading prices ...")
prices = pd.read_parquet(PRICES_PATH)
print(f"  shape      : {prices.shape}")
print(f"  date range : {prices['date'].min().date()} -> {prices['date'].max().date()}")

open_by_date = {pd.Timestamp(date): grp.set_index("symbol")["open"].to_dict() for date, grp in prices.groupby("date")}
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


print("Building Friday -> Monday pairs ...")
fri_files = sorted(
    f
    for f in os.listdir(FRI_SIG_DIR)
    if f.startswith("signals_") and f.endswith(".parquet") and os.path.isfile(os.path.join(FRI_SIG_DIR, f))
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


# ── Run each variant ───────────────────────────────────────────────────────────
all_metrics = []

for use_g6_gate, prefix, desc in VARIANTS:
    print(f"\n{'=' * 70}")
    print(f"VARIANT: {prefix}  |  USE_G6_GATE={use_g6_gate}  |  {desc}")
    print(f"{'=' * 70}")

    state = PortfolioState(initial_capital=INITIAL_CAPITAL)
    nav_path = []
    all_activity = []
    t0 = time.time()

    for i, (sig_date, exec_date, sig_path) in enumerate(mon_pairs):
        signals = pd.read_parquet(sig_path)
        exec_px = open_by_date[exec_date]

        ranked_df = compute_mr_scores(signals, use_g6_gate)

        current_holdings = set(state.holdings.keys())
        top25_symbols, action_map = reconstitute(ranked_df, current_holdings)
        top25 = list(top25_symbols)

        port_value_post, port_value_pre, activity = state.rebalance(top25, exec_px, exec_date, prefix)

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

        if (i + 1) % 100 == 0 or i == 0 or (i + 1) == len(mon_pairs):
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (len(mon_pairs) - i - 1)
            print(
                f"  [{i + 1:03d}/{len(mon_pairs)}] "
                f"sig={sig_date.date()} exec={exec_date.date()} "
                f"NAV=Rs{port_value_post / 1e6:.3f}M | "
                f"{elapsed:.0f}s elapsed {remaining:.0f}s ETA",
                flush=True,
            )

        gc.collect()

    # ── Build weekly returns df ──
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
            "exec_date": exec_dates,
            "nav": navs,
            "weekly_ret": wrets,
            "cum_ret": cum_ret.values,
            "benchmark_ret": bm_ret.values,
        }
    )
    activity_df = pd.DataFrame(all_activity)

    # ── Write CSVs ──
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
        f"Time={elapsed_total / 60:.1f}min"
    )


# ── Combined summary ───────────────────────────────────────────────────────────
summary = pd.DataFrame(all_metrics)
summary_path = f"{RESULTS_DIR}/variants_summary_{RUN_DATE}.csv"
summary.to_csv(summary_path, index=False)

print(f"\n{'=' * 90}")
print(
    f"COMBINED PERFORMANCE SUMMARY  |  Benchmark CAGR: "
    f"{all_metrics[0]['BM CAGR']:.2%}  |  {all_metrics[0]['Weeks']} weeks"
)
print(f"{'=' * 90}")
print(
    f"{'Variant':<10} {'Description':<34} {'CAGR':>7} {'Alpha':>7} "
    f"{'Sharpe':>7} {'Calmar':>7} {'MaxDD':>7} "
    f"{'Hit%':>6} {'Turn%':>6} {'AvgN':>5} {'NAV(M)':>8}"
)
print("-" * 90)
for r in all_metrics:
    print(
        f"{r['Variant']:<10} {r['Description']:<34} "
        f"{r['CAGR']:>6.2%} {r['Alpha']:>6.2%} "
        f"{r['Sharpe']:>7.3f} {r['Calmar']:>7.3f} "
        f"{r['Max DD']:>6.2%} "
        f"{r['Hit Rate']:>5.1%} {r['Avg Turnover']:>5.1%} "
        f"{r['Avg Universe']:>5.0f} "
        f"Rs{r['NAV end (M)']:>6.3f}M"
    )
print(f"\nSummary CSV -> {summary_path}")
print("=" * 90)
