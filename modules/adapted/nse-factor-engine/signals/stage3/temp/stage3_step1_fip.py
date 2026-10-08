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
Stage 3 — Step 1: Frog-in-Pan (FIP) Score
Formula: sign(ret_12m1m) x (% negative days - % positive days)
Window: T-252 -> T-21 (trading days, skip-month convention)
All 500 symbols. NaN propagates for symbols with < 253 rows.
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

# ── Slice formation window per symbol ────────────────────────────────────────
window = prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)].copy()

# ── Compute daily log returns within window ──────────────────────────────────
window = window.sort_values(["symbol", "date"])
window["log_ret"] = window.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
window = window.dropna(subset=["log_ret"])


# ── Per symbol: count positive and negative days ─────────────────────────────
def fip_components(group):
    total = len(group)
    if total == 0:
        return pd.Series({"pct_pos_days": np.nan, "pct_neg_days": np.nan})
    pos = (group["log_ret"] > 0).sum()
    neg = (group["log_ret"] < 0).sum()
    return pd.Series(
        {
            "pct_pos_days": pos / total,
            "pct_neg_days": neg / total,
        }
    )


components = (
    window.groupby("symbol", group_keys=False)
    .apply(fip_components, include_groups=False)
    .reset_index()
)

# ── Merge ret_12m1m from signals to get sign ─────────────────────────────────
components = components.merge(signals[["symbol", "ret_12m1m"]], on="symbol", how="left")

# ── Compute FIP score ─────────────────────────────────────────────────────────
components["fip_score"] = np.sign(components["ret_12m1m"]) * (
    components["pct_neg_days"] - components["pct_pos_days"]
)

# ── Re-index to all 500, NaN for insufficient history ────────────────────────
all_symbols = signals[["symbol"]].copy()
result = all_symbols.merge(
    components[["symbol", "pct_pos_days", "pct_neg_days", "fip_score"]], on="symbol", how="left"
)

# ── Sanity checks ─────────────────────────────────────────────────────────────
print("\n--- Result shape ---")
print(result.shape)

print("\n--- Null counts ---")
print(result.isnull().sum())

print("\n--- FIP score distribution ---")
print(result["fip_score"].describe())

print("\n--- pct_pos_days distribution ---")
print(result["pct_pos_days"].describe())

print("\n--- FIP range check (should be between -1 and 1) ---")
out_of_range = result[(result["fip_score"] < -1) | (result["fip_score"] > 1)]
print(f"Out of range: {len(out_of_range)} symbols")
if len(out_of_range) > 0:
    print(out_of_range)

print("\n--- Top 10 highest FIP (worst path quality) ---")
print(result.nlargest(10, "fip_score")[["symbol", "pct_pos_days", "pct_neg_days", "fip_score"]])

print("\n--- Top 10 lowest FIP (best path quality) ---")
print(result.nsmallest(10, "fip_score")[["symbol", "pct_pos_days", "pct_neg_days", "fip_score"]])

print("\n--- Day count in formation window per symbol (spot check) ---")
day_counts = window.groupby("symbol")["log_ret"].count()
print(f"Min days in window : {day_counts.min()} — {day_counts.idxmin()}")
print(f"Max days in window : {day_counts.max()} — {day_counts.idxmax()}")
print(f"Median days        : {day_counts.median():.0f}")

# ── Save ──────────────────────────────────────────────────────────────────────
out_path = f"{BASE}/signals/stage3/stage3_step1_fip.parquet"
result.to_parquet(out_path, index=False)
print(f"\nSaved: {out_path}")
print(f"Shape: {result.shape}")
print("\nSTEP 1 COMPLETE")
