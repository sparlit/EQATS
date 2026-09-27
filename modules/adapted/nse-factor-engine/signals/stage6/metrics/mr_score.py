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
Stage 6 — Momentum Ratio Scoring

Formula:
  MR12 = ret_12m1m / vol_252
  MR6  = ret_6m1m  / vol_252
  Z12, Z6 cross-sectional Z-scores
  Weighted_Z = 0.6 * Z12 + 0.4 * Z6
  Normalized_Momentum_Score:
      1 + Weighted_Z           if Weighted_Z >= 0
      1 / (1 - Weighted_Z)     if Weighted_Z <  0

Gate (g6_gate.py):
  USE_G6_GATE=1: lower_circuit_hits_63d < 3 (only circuit filter)
  USE_G6_GATE=0: all in_universe stocks

Weinstein is NOT applied here — applied in mr_reconstitute.py.

Returns scored ranked DataFrame. Gate reject DataFrame is passed through
to stage6_assemble.py for combined reject CSV writing.
"""

import pandas as pd
from g6_gate import apply_g6_gate

USE_G6_GATE = 1

# Factor weights — optimised via backtest (Jan 2016 -> Jun 2026, 126 months)
# 60/40 (12m:6m) beats 50/50 on CAGR (+1.83%), Sharpe (+0.100), MaxDD (+1.70pp)
W_12M = 0.60
W_6M = 0.40


def apply_mr_score(signals_df: pd.DataFrame) -> tuple:
    """
    Returns:
      ranked_df  — scored dataframe sorted by mr_rank
      reject_df  — gate rejects (from g6_gate), passed to assembler
    """
    required = ["symbol", "in_universe", "ret_12m1m", "ret_6m1m", "vol_252"]
    missing = [c for c in required if c not in signals_df.columns]
    assert not missing, f"mr_score: missing required columns: {missing}"

    # Step 1: in_universe filter
    df = signals_df[signals_df["in_universe"]].copy()
    print(f"in_universe stocks: {len(df)}")

    # Step 2: G6 gate (circuit filter only)
    if USE_G6_GATE == 1:
        print("USE_G6_GATE=1 — applying circuit gate (lower_circuit_hits_63d < 3)")
        n_before = len(df)
        df, reject_df = apply_g6_gate(df)
        print(f"Gate applied: {n_before} -> {len(df)} pass ({n_before - len(df)} dropped)")
    else:
        print("USE_G6_GATE=0 — no gate applied")
        import pandas as _pd

        reject_df = _pd.DataFrame(columns=["symbol", "lower_circuit_hits_63d", "rejection_stage", "rejection_reason"])

    # Step 3: Drop NaN inputs
    n_before = len(df)
    bad = df["vol_252"].isna() | (df["vol_252"] == 0) | df["ret_12m1m"].isna() | df["ret_6m1m"].isna()
    if bad.sum() > 0:
        print(
            f"WARNING: dropping {bad.sum()} rows — NaN/zero in scoring inputs: {sorted(df.loc[bad, 'symbol'].tolist())}"
        )
    df = df[~bad].copy()
    print(f"Scoring universe: {len(df)} symbols ({n_before - len(df)} dropped for NaN/zero)")

    assert len(df) >= 10, f"Too few symbols ({len(df)}) for meaningful cross-sectional Z scores"

    # Step 4: MR ratios
    df["mr_12"] = df["ret_12m1m"] / df["vol_252"]
    df["mr_6"] = df["ret_6m1m"] / df["vol_252"]

    # Step 5: Cross-sectional Z scores
    df["z_12"] = (df["mr_12"] - df["mr_12"].mean()) / df["mr_12"].std(ddof=1)
    df["z_6"] = (df["mr_6"] - df["mr_6"].mean()) / df["mr_6"].std(ddof=1)

    # Step 6: Weighted Z
    df["weighted_z"] = W_12M * df["z_12"] + W_6M * df["z_6"]

    # Step 7: Normalized score
    df["norm_momentum_score"] = df["weighted_z"].apply(lambda wz: 1 + wz if wz >= 0 else 1.0 / (1.0 - wz))

    # Step 8: Rank
    df["mr_rank"] = df["norm_momentum_score"].rank(method="min", ascending=False).astype("Int64")

    df = df.sort_values("mr_rank").reset_index(drop=True)

    print("\nScoring complete:")
    print(f"  Symbols scored   : {len(df)}")
    print(f"  norm_score range : {df['norm_momentum_score'].min():.4f} — {df['norm_momentum_score'].max():.4f}")
    print(f"  weighted_z range : {df['weighted_z'].min():.4f} — {df['weighted_z'].max():.4f}")

    return df, reject_df
