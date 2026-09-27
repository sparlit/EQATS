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
Stage 5 — FIP Re-Rank
Gray: within top decile/top-N by return, sort by FIP score.
Lower FIP = smoother path = higher quality (per Gray's convention).

Per locked design (2026-06-30): operates independently on each of the 4
Cross-Sectional Rank columns (rank_ret_12m1m, rank_simple_vol_adj_momentum,
rank_sharpe_style_momentum, rank_sortino_style_momentum). For each metric,
takes that metric's own top 100 (rank 1-100), then FIP-ranks within that
pool of 100 only. Produces 4 parallel rank_fip_<metric> columns -- not
combined, no single final selection here.

rank_fip_<metric> is 1..100 for symbols inside that metric's top 100
(1 = lowest/best FIP score), and NaN for everyone else (including
in-universe symbols outside that metric's top 100).

Requires cross_sectional_rank.py to have already run (needs its 4
rank_<metric> columns as input) plus fip_score (Stage 3).
"""
import glob
import re
import sys

import pandas as pd

RANK_METRICS = [
    "ret_12m1m",
    "simple_vol_adj_momentum",
    "sharpe_style_momentum",
    "sortino_style_momentum",
]
TOP_N = 100


def compute(signals: pd.DataFrame) -> pd.DataFrame:
    required = {f"rank_{m}" for m in RANK_METRICS} | {"fip_score", "symbol"}
    missing = required - set(signals.columns)
    assert not missing, f"signals missing required columns for FIP re-rank: {missing}"

    out = signals[["symbol"]].copy()

    for metric in RANK_METRICS:
        rank_col = f"rank_{metric}"
        fip_rank_col = f"rank_fip_{metric}"

        pool = signals[signals[rank_col] <= TOP_N].copy()
        n_pool = len(pool)
        if n_pool < TOP_N:
            print(
                f"WARNING: only {n_pool} symbols in top-{TOP_N} pool for '{metric}' "
                f"(fewer than {TOP_N} available, likely due to nulls)."
            )

        fip_ranks = pool["fip_score"].rank(method="min", ascending=True).astype("Int64")
        pool[fip_rank_col] = fip_ranks

        n_null_fip = pool["fip_score"].isnull().sum()
        if n_null_fip > 0:
            print(f"WARNING: {n_null_fip} null fip_score values within '{metric}' top-{TOP_N} pool.")

        out = out.merge(pool[["symbol", fip_rank_col]], on="symbol", how="left")
        print(f"{fip_rank_col}: {n_pool} symbols in pool, FIP-ranked 1..{fip_ranks.max()}")

    return out


if __name__ == "__main__":
    BASE = "/home/ec2-user/nse-factor-engine/"
    sys.path.insert(0, BASE + "signals/stage5/metrics")
    from cross_sectional_rank import compute as compute_rank
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
    signals = pd.read_parquet(SIGNALS_PATH)
    print(f"Signals shape: {signals.shape}")

    universe_result = compute_in_universe(signals, run_date_str, BASE)
    merged = signals.merge(universe_result, on="symbol", how="left")
    in_universe_signals = merged[merged["in_universe"]].copy()
    print(f"In-universe signals shape: {in_universe_signals.shape}")

    rank_result = compute_rank(in_universe_signals)
    in_universe_signals = in_universe_signals.merge(rank_result, on="symbol", how="left")

    fip_result = compute(in_universe_signals)

    print("\n--- FIP rank columns summary ---")
    for metric in RANK_METRICS:
        col = f"rank_fip_{metric}"
        non_null = fip_result[col].notnull().sum()
        print(f"{col}: {non_null} non-null (expected ~{TOP_N})")

    print("\n--- Sanity check: rank_fip_ret_12m1m == 1 has lowest fip_score within that pool ---")
    check = in_universe_signals.merge(fip_result, on="symbol")
    pool = check[check["rank_ret_12m1m"] <= TOP_N]
    actual_min_fip_symbol = pool.loc[pool["fip_score"].idxmin(), "symbol"]
    top1_fip_symbols = check[check["rank_fip_ret_12m1m"] == 1]["symbol"].values
    assert actual_min_fip_symbol in top1_fip_symbols, "MISMATCH: rank_fip 1 does not match actual min fip_score in pool"
    print(
        f"PASS: rank_fip_ret_12m1m==1 ({list(top1_fip_symbols)}) matches actual min fip_score in pool ({actual_min_fip_symbol})"
    )

    import os

    out_dir = BASE + "signals/stage5/intermediate/"
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_dir + f"fip_rerank_{run_date_str}.parquet"

    full_output = in_universe_signals.merge(fip_result, on="symbol", how="left")
    full_output.to_parquet(out_path, index=False)
    print(f"\nWritten: {out_path}")
    print(f"Shape: {full_output.shape}")
