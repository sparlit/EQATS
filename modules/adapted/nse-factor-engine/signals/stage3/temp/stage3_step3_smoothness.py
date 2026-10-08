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
Stage 3 — Step 3: Momentum Smoothness
Fraction of positive weeks (5-trading-day blocks) over T-252 -> T-21.
Week Open  = open price of day 1 of each 5-day block
Week Close = close price of day 5 of each 5-day block
Week is positive if Week Close > Week Open
Smoothness = positive weeks / total complete weeks
Incomplete blocks (< 5 days) dropped.
All 500 symbols. NaN for symbols with < 253 rows.
"""

import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"

# ── Load inputs ──────────────────────────────────────────────────────────────
prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
signals = pd.read_parquet(f"{BASE}/signals/stage2/momentum_core_signals_26062026.parquet")

# ── Resolve T and offsets ────────────────────────────────────────────────────
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]

print(f"T     : {T}")
print(f"T-21  : {T_21}")
print(f"T-252 : {T_252}")

# ── Slice formation window ───────────────────────────────────────────────────
window = prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)].copy()
window = window.sort_values(["symbol", "date"]).reset_index(drop=True)


# ── Build 5-day blocks per symbol ────────────────────────────────────────────
def compute_smoothness(group):
    group = group.reset_index(drop=True)
    n = len(group)
    complete_weeks = n // 5
    if complete_weeks == 0:
        return pd.Series({"smoothness": np.nan, "total_weeks": 0, "positive_weeks": 0})
    pos_weeks = 0
    for i in range(complete_weeks):
        start = i * 5
        end = start + 4
        week_open = group.loc[start, "open"]
        week_close = group.loc[end, "close"]
        if week_close > week_open:
            pos_weeks += 1
    smoothness = pos_weeks / complete_weeks
    return pd.Series(
        {
            "smoothness": smoothness,
            "total_weeks": complete_weeks,
            "positive_weeks": pos_weeks,
        }
    )


result = (
    window.groupby("symbol", group_keys=False)
    .apply(compute_smoothness, include_groups=False)
    .reset_index()
)

# ── Re-index to all 500, NaN for insufficient history ────────────────────────
all_symbols = signals[["symbol"]].copy()
result = all_symbols.merge(result, on="symbol", how="left")

# ── Sanity checks ────────────────────────────────────────────────────────────
print("\n--- Shape ---")
print(result.shape)

print("\n--- Null counts ---")
print(result.isnull().sum())

print("\n--- Smoothness distribution ---")
print(result["smoothness"].describe())

print("\n--- Total weeks distribution ---")
print(result["total_weeks"].describe())

print("\n--- Range check (smoothness 0 to 1) ---")
out_of_range = result[(result["smoothness"] < 0) | (result["smoothness"] > 1)]
print(f"Out of range: {len(out_of_range)} symbols")

print("\n--- Top 10 highest smoothness (most consistent) ---")
print(result.nlargest(10, "smoothness")[["symbol", "smoothness", "total_weeks", "positive_weeks"]])

print("\n--- Top 10 lowest smoothness (least consistent) ---")
print(result.nsmallest(10, "smoothness")[["symbol", "smoothness", "total_weeks", "positive_weeks"]])

# ── Save ─────────────────────────────────────────────────────────────────────
out_path = f"{BASE}/signals/stage3/stage3_step3_smoothness.parquet"
result[["symbol", "smoothness"]].to_parquet(out_path, index=False)
print(f"\nSaved: {out_path}")
print(f"Shape: {result[['symbol', 'smoothness']].shape}")
print("\nSTEP 3 COMPLETE")
