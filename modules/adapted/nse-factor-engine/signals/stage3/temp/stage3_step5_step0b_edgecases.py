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
Stage 3 Step 5 — Step 0b: Clarify edge cases before writing metric
"""
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"

prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
meta = pd.read_parquet(f"{BASE}/data/universe_metadata.parquet")
s3 = pd.read_parquet(f"{BASE}/signals/stage3/momentum_quality_signals_25062026.parquet")

# Safe T resolution
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]

window = prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)].copy()
sym_counts = window.groupby("symbol")["date"].count()

# ── 1. Null industry symbol ────────────────────────────────────────────────
null_ind = meta[meta["industry"].isna()]
print("=== Symbol with null industry ===")
print(null_ind.to_string())
print(f"  Row count in window: {sym_counts.get(null_ind['symbol'].iloc[0], 'NOT FOUND')}")

# ── 2. Which symbols have NaN fip_score ────────────────────────────────────
nan_fip = s3[s3["fip_score"].isna()]["symbol"].tolist()
print(f"\n=== Symbols with NaN fip_score ({len(nan_fip)}) ===")
print(sorted(nan_fip))

# Their row counts in the window
nan_fip_counts = sym_counts[sym_counts.index.isin(nan_fip)].sort_values()
print("\n  Row counts for NaN-fip symbols:")
print(nan_fip_counts.to_string())

# What was the min row count among non-NaN fip symbols?
valid_fip = s3[s3["fip_score"].notna()]["symbol"].tolist()
valid_counts = sym_counts[sym_counts.index.isin(valid_fip)]
print(f"\n  Min rows among valid-fip symbols : {valid_counts.min()}")
print(f"  Max rows among NaN-fip symbols   : {nan_fip_counts.max()}")
print(f"  --> Effective NaN cutoff is between {nan_fip_counts.max()} and {valid_counts.min()} rows")

# ── 3. Sector sizes (for awareness of thin sectors) ───────────────────────
print("\n=== Sector sizes (symbols per industry) ===")
print(meta.groupby("industry")["symbol"].count().sort_values().to_string())
