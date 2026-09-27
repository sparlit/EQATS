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
Stage 3 — Step 0: Inspect Inputs
Inspect prices.parquet and momentum_core_signals_26062026.parquet
before any metric math.
"""

import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"

# ── Load files ──────────────────────────────────────────────────────────────
print("=" * 60)
print("LOADING FILES")
print("=" * 60)

prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
signals = pd.read_parquet(f"{BASE}/signals/stage2/momentum_core_signals_26062026.parquet")

print(f"prices.parquet       : {prices.shape[0]:,} rows × {prices.shape[1]} cols")
print(f"momentum signals     : {signals.shape[0]:,} rows × {signals.shape[1]} cols")

# ── prices.parquet ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("PRICES — SCHEMA & BASICS")
print("=" * 60)

print(f"\nColumns      : {list(prices.columns)}")
print(f"Dtypes:\n{prices.dtypes}")
print(f"\nDate range   : {prices['date'].min()} → {prices['date'].max()}")
print(f"Symbols      : {prices['symbol'].nunique()}")
print(f"Total rows   : {prices.shape[0]:,}")

print("\n--- Null counts ---")
print(prices.isnull().sum())

print("\n--- Duplicate (symbol, date) pairs ---")
dupes = prices.duplicated(subset=["symbol", "date"]).sum()
print(f"Duplicates   : {dupes}")

print("\n--- Sample (5 rows) ---")
print(prices.head())

# ── Trading day count per symbol ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("PRICES — TRADING DAY COUNTS PER SYMBOL")
print("=" * 60)

counts = prices.groupby("symbol")["date"].count().sort_values()
print(f"Min rows (symbol)  : {counts.min()} — {counts.idxmin()}")
print(f"Max rows (symbol)  : {counts.max()} — {counts.idxmax()}")
print(f"Median rows        : {counts.median():.0f}")
print(f"Symbols < 253 rows : {(counts < 253).sum()}")
print(f"Symbols < 126 rows : {(counts < 126).sum()}")
print(f"Symbols < 63 rows  : {(counts < 63).sum()}")

# ── T and key offsets ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("PRICES — T AND KEY TRADING DAY OFFSETS")
print("=" * 60)

all_dates = sorted(prices["date"].unique())
T = all_dates[-1]
print(f"T (latest date)    : {T}")


def offset_date(dates, n):
    if len(dates) >= n + 1:
        return dates[-(n + 1)]
    return None


T_21 = offset_date(all_dates, 21)
T_63 = offset_date(all_dates, 63)
T_126 = offset_date(all_dates, 126)
T_252 = offset_date(all_dates, 252)

print(f"T-21  (skip-month) : {T_21}")
print(f"T-63  (3M anchor)  : {T_63}")
print(f"T-126 (6M anchor)  : {T_126}")
print(f"T-252 (12M anchor) : {T_252}")
print(f"Total trading days in prices: {len(all_dates)}")

# ── momentum_core_signals ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("MOMENTUM SIGNALS — SCHEMA & BASICS")
print("=" * 60)

print(f"\nColumns:\n{list(signals.columns)}")
print(f"\nDtypes:\n{signals.dtypes}")
print(f"\nas_of_date values  : {signals['as_of_date'].unique()}")
print(f"Symbols            : {signals['symbol'].nunique()}")

print("\n--- Null counts ---")
print(signals.isnull().sum())

print("\n--- data_quality_flag ---")
print(signals["data_quality_flag"].value_counts())

print("\n--- Sample (5 rows) ---")
print(signals[["symbol", "ret_12m1m", "vol_231", "sharpe_style_momentum"]].head())

# ── Symbol alignment ─────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("SYMBOL ALIGNMENT — prices vs signals")
print("=" * 60)

price_syms = set(prices["symbol"].unique())
signal_syms = set(signals["symbol"].unique())

in_prices_not_signals = price_syms - signal_syms
in_signals_not_prices = signal_syms - price_syms

print(f"Symbols in prices          : {len(price_syms)}")
print(f"Symbols in signals         : {len(signal_syms)}")
print(f"In prices, not in signals  : {len(in_prices_not_signals)} — {in_prices_not_signals or 'none'}")
print(f"In signals, not in prices  : {len(in_signals_not_prices)} — {in_signals_not_prices or 'none'}")

# ── Formation window availability check ──────────────────────────────────────
print("\n" + "=" * 60)
print("FORMATION WINDOW CHECK (T-252 → T-21 per symbol)")
print("=" * 60)

symbol_dates = prices.groupby("symbol")["date"].apply(set)

has_T21 = []
has_T252 = []
for dates in symbol_dates.values():
    has_T21.append(T_21 in dates)
    has_T252.append(T_252 in dates)

print(f"Symbols with data at T-21  : {sum(has_T21)}")
print(f"Symbols with data at T-252 : {sum(has_T252)}")
print(f"Symbols with BOTH          : {sum(a and b for a, b in zip(has_T21, has_T252, strict=False))}")

print("\n" + "=" * 60)
print("STEP 0 COMPLETE")
print("=" * 60)
