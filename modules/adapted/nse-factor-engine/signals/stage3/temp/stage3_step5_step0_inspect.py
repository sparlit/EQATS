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
Stage 3 Step 5 — Residual Momentum
STEP 0: Input Inspection

Run from: /home/ec2-user/nse-factor-engine/
    python3 signals/stage3/stage3_step5_step0_inspect.py
"""

import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"

# ── 1. prices ──────────────────────────────────────────────────────────────
prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
print("=== prices.parquet ===")
print(f"  Shape        : {prices.shape}")
print(f"  Columns      : {list(prices.columns)}")
print(f"  Date range   : {prices['date'].min()} → {prices['date'].max()}")
print(f"  Unique syms  : {prices['symbol'].nunique()}")

# Safe T resolution
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]
print(f"\n  T            : {T}")
print(f"  T-21         : {T_21}")
print(f"  T-252        : {T_252}")
print(f"  Window length: {len([d for d in all_dates if T_252 <= d <= T_21])} trading days")

window = prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)].copy()
print(f"  Window rows  : {window.shape[0]}")
print(f"  Syms in window: {window['symbol'].nunique()}")

# Check for NaNs in close within window
nan_close = window[window["close"].isna()][["symbol", "date", "close"]]
print(f"\n  NaN close in window: {len(nan_close)} rows")
if len(nan_close) > 0:
    print(nan_close.head(10).to_string())

# Row counts per symbol in window
sym_counts = window.groupby("symbol")["date"].count()
print(f"\n  Rows per symbol in window — min:{sym_counts.min()}  max:{sym_counts.max()}  median:{sym_counts.median()}")
short_syms = sym_counts[sym_counts < 230].sort_values()
print(f"  Symbols with < 230 rows: {len(short_syms)}")
if len(short_syms) > 0:
    print(short_syms.to_string())

# ── 2. universe_metadata ───────────────────────────────────────────────────
print("\n=== universe_metadata.parquet ===")
meta = pd.read_parquet(f"{BASE}/data/universe_metadata.parquet")
print(f"  Shape    : {meta.shape}")
print(f"  Columns  : {list(meta.columns)}")
print(f"  dtypes:\n{meta.dtypes}")
print("\n  Industry value_counts (top 20):")
print(meta["industry"].value_counts().head(20).to_string())
print(f"\n  Total industries: {meta['industry'].nunique()}")
print(f"  Symbols with null industry: {meta['industry'].isna().sum()}")

# Check all 500 symbols in metadata are in prices window
price_syms = set(window["symbol"].unique())
meta_syms = set(meta["symbol"].unique())
print(f"\n  In meta but not in window: {sorted(meta_syms - price_syms)}")
print(f"  In window but not in meta: {len(price_syms - meta_syms)} symbols")

# ── 3. existing stage3 parquet ─────────────────────────────────────────────
print("\n=== momentum_quality_signals_25062026.parquet ===")
s3 = pd.read_parquet(f"{BASE}/signals/stage3/momentum_quality_signals_25062026.parquet")
print(f"  Shape   : {s3.shape}")
print(f"  Columns : {list(s3.columns)}")
print(f"  Head:\n{s3.head(3).to_string()}")
print(f"\n  NaN counts:\n{s3.isna().sum().to_string()}")

print("\n=== Step 0 complete — no issues above means safe to proceed ===")
