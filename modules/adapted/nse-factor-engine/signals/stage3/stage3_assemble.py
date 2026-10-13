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
Stage 3 — Assembler: Momentum Quality Signals
Imports each metric from signals/stage3/metrics/.
Inputs : data/prices.parquet
         data/universe_metadata.parquet
         signals/stage2/momentum_core_signals_{AS_OF}.parquet
Output : signals/stage3/momentum_quality_signals_{AS_OF}.parquet
         signals/final/momentum_signals_final_{AS_OF}.parquet
Columns: symbol, as_of_date, fip_score, pct_pos_days, pct_neg_days,
         smoothness, proximity_52w_high, residual_momentum, rm_r2, rm_n_obs,
         industry_cum_ret, industry_rank, weinstein_stage2,
         alpha_12m1m_ew, alpha_12m1m_industry, momentum_rank_12m1m,
         rsi_14, rsi_7,
         ema_20, ema_50, dist_ema_20, dist_ema_50,
         mfi_14,
         stoch_rsi_k, stoch_rsi_d,
         bb_middle, bb_upper, bb_lower, bb_pct_b,
         bb_bandwidth_curr_wk, bb_bandwidth_prev_wk,
         bb_bandwidth_prev_2wk, bb_bandwidth_prev_3wk, bb_squeeze
"""

import os
import sys

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"
sys.path.insert(0, BASE)

from signals.stage3.metrics.bollinger import compute as compute_bollinger
from signals.stage3.metrics.ema_distance import compute as compute_ema_distance
from signals.stage3.metrics.fip import compute as compute_fip
from signals.stage3.metrics.leading_industry import compute as compute_leading_industry
from signals.stage3.metrics.mfi import compute as compute_mfi
from signals.stage3.metrics.proximity import compute as compute_proximity
from signals.stage3.metrics.relative_strength import compute as compute_relative_strength
from signals.stage3.metrics.residual_momentum import compute as compute_residual_momentum
from signals.stage3.metrics.rsi import compute as compute_rsi
from signals.stage3.metrics.smoothness import compute as compute_smoothness
from signals.stage3.metrics.stoch_rsi import compute as compute_stoch_rsi
from signals.stage3.metrics.weinstein import compute as compute_weinstein

# ── Load ──────────────────────────────────────────────────────────────────────────────
prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
meta = pd.read_parquet(f"{BASE}/data/universe_metadata.parquet")

# ── Resolve T ──────────────────────────────────────────────────────────────────────────
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]
AS_OF = T.strftime("%d%m%Y")

import zoneinfo
from datetime import datetime as _dt

RUN_DATE_STR = _dt.now(zoneinfo.ZoneInfo("Asia/Kolkata")).date().strftime("%d%m%Y")

print(f"T     : {T.date()}")
print(f"T-21  : {T_21.date()}")
print(f"T-252 : {T_252.date()}")
print(f"AS_OF : {AS_OF}")

# ── Load stage 2 signals ──────────────────────────────────────────────────────────────────────
signals = pd.read_parquet(f"{BASE}/signals/stage2/momentum_core_signals_{RUN_DATE_STR}.parquet")
print(f"Stage 2 signals loaded: {signals.shape}")

# ── Formation window T-252 → T-21 ──────────────────────────────────────────────────────────────────
window = (
    prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)]
    .copy()
    .sort_values(["symbol", "date"])
    .reset_index(drop=True)
)

# ── Compute metrics ─────────────────────────────────────────────────────────────────────────────
print("Computing FIP...")
fip_df = compute_fip(window, signals)

print("Computing smoothness...")
smooth_df = compute_smoothness(window)

print("Computing 52w proximity...")
prox_df = compute_proximity(prices, T, T_252)

print("Computing residual momentum...")
rm_df = compute_residual_momentum(window, meta)

print("Computing leading industry...")
li_df = compute_leading_industry(window, meta)

print("Computing Weinstein stage...")
ws_df = compute_weinstein(prices, T)

print("Computing relative strength (alpha/momentum)...")
rs_df = compute_relative_strength(window, meta)

print("Computing RSI (N=14 and N=7)...")
rsi_df = compute_rsi(prices, T)

print("Computing EMA distance (20 and 50)...")
ema_df = compute_ema_distance(prices, T)

print("Computing MFI-14...")
mfi_df = compute_mfi(prices, T)

print("Computing Stochastic RSI (%K and %D)...")
srsi_df = compute_stoch_rsi(prices, T)

print("Computing Bollinger Bands...")
bb_df = compute_bollinger(prices, T)

# ── Assemble ─────────────────────────────────────────────────────────────────────────────────
result = signals[["symbol"]].copy()
result = result.merge(meta[["symbol", "industry"]], on="symbol", how="left")
result = result.merge(fip_df, on="symbol", how="left")
result = result.merge(smooth_df, on="symbol", how="left")
result = result.merge(prox_df, on="symbol", how="left")
result = result.merge(rm_df, on="symbol", how="left")
result = result.merge(li_df, on="symbol", how="left")
result = result.merge(ws_df, on="symbol", how="left")
result = result.merge(rs_df, on="symbol", how="left")
result = result.merge(rsi_df, on="symbol", how="left")
result = result.merge(ema_df, on="symbol", how="left")
result = result.merge(mfi_df, on="symbol", how="left")
result = result.merge(srsi_df, on="symbol", how="left")
result = result.merge(bb_df, on="symbol", how="left")
result.insert(1, "as_of_date", T)

# ── Final checks ───────────────────────────────────────────────────────────────────────────────
print("\n--- Shape ---")
print(result.shape)

print("\n--- Columns ---")
print(list(result.columns))

print("\n--- Null counts ---")
print(result.isnull().sum().to_string())

print("\n--- Distributions ---")
for col in [
    "fip_score",
    "pct_pos_days",
    "pct_neg_days",
    "smoothness",
    "proximity_52w_high",
    "residual_momentum",
    "industry_cum_ret",
    "industry_rank",
    "alpha_12m1m_ew",
    "alpha_12m1m_industry",
    "momentum_rank_12m1m",
    "rsi_14",
    "rsi_7",
    "ema_20",
    "ema_50",
    "dist_ema_20",
    "dist_ema_50",
    "mfi_14",
    "stoch_rsi_k",
    "stoch_rsi_d",
    "bb_pct_b",
    "bb_bandwidth_curr_wk",
    "bb_bandwidth_prev_wk",
    "bb_bandwidth_prev_2wk",
    "bb_bandwidth_prev_3wk",
]:
    print(f"\n{col}:")
    print(result[col].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).to_string())

print("\nweinstein_stage2 value counts:")
print(result["weinstein_stage2"].value_counts().to_string())

print("\nbb_squeeze value counts:")
print(result["bb_squeeze"].value_counts(dropna=False).to_string())

print(f"\nTotal symbols : {result['symbol'].nunique()}")
print(f"Total rows    : {len(result)}")

# ── Save stage3 parquet ──────────────────────────────────────────────────────────────────────────────
out_path = f"{BASE}/signals/stage3/momentum_quality_signals_{RUN_DATE_STR}.parquet"
result.to_parquet(out_path, index=False)
print(f"\nSaved stage3: {out_path}")
print(f"Shape: {result.shape}")

# ── Merge stage2 + stage3 and save to final ───────────────────────────────────────────────────────────────────
os.makedirs(f"{BASE}/signals/final", exist_ok=True)
final = signals.merge(result.drop(columns=["as_of_date"]), on="symbol", how="left")
final_path = f"{BASE}/signals/final/momentum_signals_final_{RUN_DATE_STR}.parquet"
final.to_parquet(final_path, index=False)
print(f"Saved final : {final_path}")
print(f"Shape: {final.shape}")
print("\nASSEMBLER COMPLETE")
