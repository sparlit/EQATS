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
Stage 5 — Cross-Sectional Rank
Gray: rank all stocks in universe by return.

Per locked design: ranks computed on the in-universe-filtered population
across 4 separate metrics, independently, no combining, no top-N cutoff
here (that's a later step). Rank 1 = best (highest value), ties via
method='min'.

Runnable two ways:
  1. Imported:  from cross_sectional_rank import compute
  2. Standalone: python3 cross_sectional_rank.py
     -> resolves latest signals file, runs in_universe + this metric,
        writes signals/stage5/intermediate/cross_sectional_rank_{run_date}.parquet
        for inspection. This output is NOT the final Stage 5 file -- the
        real assembler (built later) will merge all Stage 5 metrics
        together and write to signals/final/.
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
    "alpha_12m1m_ew",
    "alpha_12m1m_industry",
]


def compute(signals: pd.DataFrame) -> pd.DataFrame:
    missing = set(RANK_METRICS) - set(signals.columns)
    assert not missing, f"signals missing required columns for ranking: {missing}"

    out = signals[["symbol"]].copy()

    for metric in RANK_METRICS:
        rank_col = f"rank_{metric}"
        out[rank_col] = signals[metric].rank(method="min", ascending=False).astype("Int64")
        n_null_input = signals[metric].isnull().sum()
        if n_null_input > 0:
            print(
                f"WARNING: {n_null_input} null values in '{metric}' before ranking "
                f"-- these rank as NaN."
            )

    print(f"Ranked {len(out)} in-universe symbols on {len(RANK_METRICS)} metrics: {RANK_METRICS}")
    return out


if __name__ == "__main__":
    BASE = "/home/ec2-user/nse-factor-engine/"
    sys.path.insert(0, BASE + "signals/stage5/metrics")
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
    dated.sort(
        key=lambda x: pd.Timestamp(day=int(x[0][:2]), month=int(x[0][2:4]), year=int(x[0][4:]))
    )
    run_date_str, SIGNALS_PATH = dated[-1]

    print(f"Using signals file run_date: {run_date_str}")
    print(f"Signals path: {SIGNALS_PATH}")
    signals = pd.read_parquet(SIGNALS_PATH)
    print(f"Signals shape: {signals.shape}")

    universe_result = compute_in_universe(signals, run_date_str, BASE)
    merged = signals.merge(universe_result, on="symbol", how="left")
    in_universe_signals = merged[merged["in_universe"]].copy()
    print(f"In-universe signals shape: {in_universe_signals.shape}")

    rank_result = compute(in_universe_signals)

    print("\n--- Rank range check ---")
    for metric in RANK_METRICS:
        col = f"rank_{metric}"
        print(
            f"{col}: min={rank_result[col].min()}, max={rank_result[col].max()}, n_unique={rank_result[col].nunique()}"
        )

    check = in_universe_signals.merge(rank_result, on="symbol")
    actual_max_symbol = check.loc[check["ret_12m1m"].idxmax(), "symbol"]
    top1_symbols = check[check["rank_ret_12m1m"] == 1]["symbol"].values
    assert actual_max_symbol in top1_symbols, "MISMATCH: rank 1 does not match actual max ret_12m1m"
    print(
        f"PASS: rank 1 ({list(top1_symbols)}) matches actual max ret_12m1m symbol ({actual_max_symbol})"
    )

    import os

    out_dir = BASE + "signals/stage5/intermediate/"
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_dir + f"cross_sectional_rank_{run_date_str}.parquet"

    full_output = in_universe_signals.merge(rank_result, on="symbol", how="left")
    full_output.to_parquet(out_path, index=False)
    print(f"\nWritten: {out_path}")
    print(f"Shape: {full_output.shape}")
