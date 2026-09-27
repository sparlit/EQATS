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
Stage 3 — Step 4: 52-Week High Proximity
Formula: close[T] / max(high, T-252 -> T)
T = latest date with >= 490 symbols (no skip-month — George & Hwang 2004)
All 500 symbols. NaN for symbols with < 253 rows (can't reach T-252).
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
T_252 = all_dates[-253]

print(f"T     : {T}")
print(f"T-252 : {T_252}")

# ── Verify rows at T ─────────────────────────────────────────────────────────
rows_at_T = prices[prices["date"] == T]
print(f"Rows at T: {len(rows_at_T)}")

# ── close[T] per symbol ──────────────────────────────────────────────────────
close_T = rows_at_T[["symbol", "close"]].rename(columns={"close": "close_T"})

# ── max(high) over T-252 -> T per symbol ────────────────────────────────────
window = prices[(prices["date"] >= T_252) & (prices["date"] <= T)]
high_52w = window.groupby("symbol")["high"].max().reset_index().rename(columns={"high": "high_52w"})

# ── Merge and compute proximity ──────────────────────────────────────────────
result = signals[["symbol"]].copy()
result = result.merge(close_T, on="symbol", how="left")
result = result.merge(high_52w, on="symbol", how="left")

result["proximity_52w_high"] = result["close_T"] / result["high_52w"]

# ── Sanity checks ────────────────────────────────────────────────────────────
print("\n--- Shape ---")
print(result.shape)

print("\n--- Null counts ---")
print(result.isnull().sum())

print("\n--- Proximity distribution ---")
print(result["proximity_52w_high"].describe())

print("\n--- Range check (should be 0 to 1) ---")
above_1 = result[result["proximity_52w_high"] > 1]
print(f"Above 1: {len(above_1)} symbols")
if len(above_1) > 0:
    print(above_1[["symbol", "close_T", "high_52w", "proximity_52w_high"]])

print("\n--- Top 10 highest proximity (closest to 52w high) ---")
print(result.nlargest(10, "proximity_52w_high")[["symbol", "close_T", "high_52w", "proximity_52w_high"]])

print("\n--- Top 10 lowest proximity (furthest from 52w high) ---")
print(result.nsmallest(10, "proximity_52w_high")[["symbol", "close_T", "high_52w", "proximity_52w_high"]])

# ── Save ─────────────────────────────────────────────────────────────────────
out_path = f"{BASE}/signals/stage3/stage3_step4_52wk_high.parquet"
result[["symbol", "proximity_52w_high"]].to_parquet(out_path, index=False)
print(f"\nSaved: {out_path}")
print(f"Shape: {result[['symbol', 'proximity_52w_high']].shape}")
print("\nSTEP 4 COMPLETE")
