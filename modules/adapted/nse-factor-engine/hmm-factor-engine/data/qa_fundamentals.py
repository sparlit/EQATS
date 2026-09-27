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
qa_fundamentals.py
==================
Quick QA on fundamentals_annual.parquet.
Run from the directory containing the parquet file, or pass path as arg.

Usage:
    python qa_fundamentals.py
    python qa_fundamentals.py /path/to/fundamentals_annual.parquet
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Load ──────────────────────────────────────────────────────────────────────
path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fundamentals_annual.parquet")
if not path.exists():
    print(f"[ERROR] File not found: {path}")
    sys.exit(1)

df = pd.read_parquet(path)
print(f"\n{'=' * 60}")
print(f"  FILE: {path.resolve()}")
print(f"{'=' * 60}")

# ── 1. Shape & Schema ─────────────────────────────────────────────────────────
print("\n── Shape ──────────────────────────────────────────────────")
print(f"  Rows    : {len(df):,}")
print(f"  Columns : {list(df.columns)}")

# ── 2. Unique tickers & years ─────────────────────────────────────────────────
print("\n── Coverage ───────────────────────────────────────────────")
print(f"  Unique tickers     : {df['nse_ticker'].nunique()}")
print(f"  Unique fiscal years: {df['fiscal_year'].nunique()}")
print(f"  Fiscal years       : {sorted(df['fiscal_year'].dropna().unique())}")

# ── 3. Null counts per column ─────────────────────────────────────────────────
print("\n── Null counts ────────────────────────────────────────────")
nulls = df.isnull().sum()
total = len(df)
for col, n in nulls.items():
    pct = n / total * 100
    bar = "█" * int(pct / 5)
    print(f"  {col:<15} {n:>6} nulls ({pct:5.1f}%)  {bar}")

# ── 4. Tickers with zero data ─────────────────────────────────────────────────
numeric_cols = ["sales", "raw_material", "net_profit", "eps", "shares_cr", "book_equity", "total_debt"]
all_null = df.groupby("nse_ticker")[numeric_cols].apply(lambda g: g.isnull().all().all())
empty_tickers = all_null[all_null].index.tolist()
print("\n── Tickers with ALL nulls (no usable data) ────────────────")
print(f"  Count: {len(empty_tickers)}")
if empty_tickers:
    print(f"  {empty_tickers}")

# ── 5. Sample rows — well-known tickers ───────────────────────────────────────
print("\n── Sample rows (RELIANCE, HDFCBANK, INFY, TCS) ───────────")
sample_tickers = ["RELIANCE", "HDFCBANK", "INFY", "TCS"]
sample = df[df["nse_ticker"].isin(sample_tickers)].sort_values(["nse_ticker", "fiscal_year"])
if sample.empty:
    print("  None of the sample tickers found in data.")
else:
    print(sample.to_string(index=False))

# ── 6. Sanity checks ──────────────────────────────────────────────────────────
print("\n── Sanity checks ──────────────────────────────────────────")

# Sales should be positive
neg_sales = df[df["sales"] < 0]
print(f"  Rows with negative sales    : {len(neg_sales)}")
if len(neg_sales):
    print(f"    {neg_sales[['nse_ticker', 'fiscal_year', 'sales']].head(5).to_string(index=False)}")

# EPS extremes
print(f"  EPS range: {df['eps'].min():.2f} to {df['eps'].max():.2f}")

# Shares_cr — should be > 0
bad_shares = df[df["shares_cr"] <= 0]
print(f"  Rows with shares_cr <= 0    : {len(bad_shares)}")

# Book equity negatives (distressed companies — allowed but worth flagging)
neg_equity = df[df["book_equity"] < 0]
print(f"  Rows with negative equity   : {len(neg_equity)} (distressed cos)")
if len(neg_equity):
    print(f"    {neg_equity['nse_ticker'].unique().tolist()}")

# ── 7. Year coverage per ticker ───────────────────────────────────────────────
print("\n── Year coverage distribution ─────────────────────────────")
years_per_ticker = df.groupby("nse_ticker")["fiscal_year"].count()
print(years_per_ticker.describe().to_string())
print(f"\n  Tickers with < 3 years of data: {(years_per_ticker < 3).sum()}")
print(f"  Tickers with >= 7 years       : {(years_per_ticker >= 7).sum()}")

# ── 8. Latest year check ──────────────────────────────────────────────────────
print("\n── Latest fiscal year per ticker (top 10) ─────────────────")
latest = df.groupby("nse_ticker")["fiscal_year"].max().sort_values(ascending=True)
print(f"  Oldest latest year: {latest.iloc[0]}  ({latest.index[0]})")
print(f"  Most common latest year: {latest.mode()[0]}")
stale = latest[latest < "Mar'23"].index.tolist()
print(f"  Tickers whose latest data is before Mar'23: {len(stale)}")
if stale:
    print(f"    {stale}")

print(f"\n{'=' * 60}\n")
