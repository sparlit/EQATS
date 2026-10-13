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
Stage 3 — Step 2: % Positive Return Days
Already computed in Step 1. This step reads Step 1 output,
extracts pct_pos_days as a standalone signal, sanity checks, and saves.
Window: T-252 -> T-21 (same formation window as FIP)
All 500 symbols. NaN propagates for symbols with < 253 rows.
"""

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"

# ── Load Step 1 output ───────────────────────────────────────────────────────
fip = pd.read_parquet(f"{BASE}/signals/stage3/stage3_step1_fip.parquet")

# ── Extract pct_pos_days ─────────────────────────────────────────────────────
result = fip[["symbol", "pct_pos_days"]].copy()

# ── Sanity checks ────────────────────────────────────────────────────────────
print("--- Shape ---")
print(result.shape)

print("\n--- Null counts ---")
print(result.isnull().sum())

print("\n--- Distribution ---")
print(result["pct_pos_days"].describe())

print("\n--- Range check (should be 0 to 1) ---")
out_of_range = result[(result["pct_pos_days"] < 0) | (result["pct_pos_days"] > 1)]
print(f"Out of range: {len(out_of_range)} symbols")

print("\n--- Top 10 highest pct_pos_days (most positive days) ---")
print(result.nlargest(10, "pct_pos_days"))

print("\n--- Top 10 lowest pct_pos_days (fewest positive days) ---")
print(result.nsmallest(10, "pct_pos_days"))

# ── Save ─────────────────────────────────────────────────────────────────────
out_path = f"{BASE}/signals/stage3/stage3_step2_pct_pos_days.parquet"
result.to_parquet(out_path, index=False)
print(f"\nSaved: {out_path}")
print(f"Shape: {result.shape}")
print("\nSTEP 2 COMPLETE")
