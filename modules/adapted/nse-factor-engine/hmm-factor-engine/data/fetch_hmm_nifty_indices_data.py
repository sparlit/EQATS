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
fetch_hmm_nifty_indices_data.py
================================
Reads ^CRSLDX daily data from the shared index parquet (single source of truth),
computes monthly HMM features, and saves nifty500_hmm_data.parquet.

Input  : data/index_prices.parquet  (repo root, written by data/fetch_index_data.py)
Output : hmm-factor-engine/data/nifty500_hmm_data.parquet  (schema unchanged)

Sector indices (^CNXAUTO, ^NSEBANK, ^CNXIT, etc.) are dropped -- not used
downstream by any active production script.

Columns (HMM features):
  excess_return      : monthly index return minus monthly risk-free rate
  realised_vol       : annualised std dev of daily returns within each month
  trailing_2m_return : 2-month cumulative return

Audit columns:
  monthly_return : raw monthly return
  rfr_monthly    : monthly risk-free rate used (annual rate / 12)

Risk-Free Rate schedule:
  2000-01 to 2011-12 : 8.0% pa
  2012-01 to 2019-12 : 7.0% pa
  2020-01 to 2021-12 : 5.0% pa
  2022-01 onwards    : 7.0% pa

Usage:
  python3 hmm-factor-engine/data/fetch_hmm_nifty_indices_data.py
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────
# Must be run from repo root
if not Path("signals").is_dir():
    sys.exit("ERROR: run from repo root: cd /home/ec2-user/nse-factor-engine/")

INDEX_PARQUET = Path("data/index_prices.parquet")
OUTPUT_FILE = Path("hmm-factor-engine/data/nifty500_hmm_data.parquet")
TICKER = "^CRSLDX"
HMM_FEATURES = ["excess_return", "realised_vol", "trailing_2m_return"]

# ── Staleness check ───────────────────────────────
if not INDEX_PARQUET.exists():
    sys.exit(f"ERROR: {INDEX_PARQUET} not found.\nRun data/fetch_index_data.py first.")

index_mtime = date.fromtimestamp(INDEX_PARQUET.stat().st_mtime)
if index_mtime < date.today():
    sys.exit(f"ERROR: {INDEX_PARQUET} is stale (last modified {index_mtime}).\nRun data/fetch_index_data.py first.")

# ── Risk-free rate schedule ───────────────────────
RFR_SCHEDULE = [
    ("2000-01", "2011-12", 0.080),
    ("2012-01", "2019-12", 0.070),
    ("2020-01", "2021-12", 0.050),
    ("2022-01", "2099-12", 0.070),
]


def build_rfr_series(index):
    rfr = pd.Series(np.nan, index=index, name="rfr_monthly")
    for start, end, annual_rate in RFR_SCHEDULE:
        mask = (index >= pd.Period(start, "M").to_timestamp()) & (index <= pd.Period(end, "M").to_timestamp(how="end"))
        rfr[mask] = annual_rate / 12
    n_missing = rfr.isna().sum()
    if n_missing > 0:
        print(f"    WARNING: {n_missing} month(s) have no RFR mapping")
    return rfr


def compute_monthly_features(daily):
    daily = daily.copy()
    daily["daily_return"] = daily["close"].pct_change()

    monthly_close = daily["close"].resample("ME").last()
    monthly_return = monthly_close.pct_change()
    monthly_return.name = "monthly_return"

    realised_vol = daily["daily_return"].resample("ME").std() * np.sqrt(252)
    realised_vol.name = "realised_vol"

    trailing_2m = (1 + monthly_return).rolling(2).apply(lambda x: x.prod(), raw=True) - 1
    trailing_2m.name = "trailing_2m_return"

    df = pd.concat([monthly_return, realised_vol, trailing_2m], axis=1)
    df.index.name = "date"
    return df


def main():
    print("=" * 60)
    print("fetch_hmm_nifty_indices_data — reading from shared parquet")
    print("=" * 60)

    # Load and filter to ^CRSLDX
    prices = pd.read_parquet(INDEX_PARQUET)
    prices["date"] = pd.to_datetime(prices["date"])
    daily = prices[prices["symbol"] == TICKER][["date", "close"]].copy()
    daily = daily.sort_values("date").set_index("date")

    if daily.empty:
        sys.exit(f"ERROR: {TICKER} not found in {INDEX_PARQUET}")

    print(f"\n  {TICKER} daily rows : {daily.index[0].date()} -> {daily.index[-1].date()}")

    monthly = compute_monthly_features(daily)
    rfr = build_rfr_series(monthly.index)
    monthly["rfr_monthly"] = rfr
    monthly["excess_return"] = monthly["monthly_return"] - monthly["rfr_monthly"]

    monthly = monthly.dropna(subset=HMM_FEATURES)
    monthly = monthly[[*HMM_FEATURES, "monthly_return", "rfr_monthly"]]

    print(f"  Monthly rows  : {monthly.index[0].date()} -> {monthly.index[-1].date()}")
    print(f"  Null counts   : {monthly.isna().sum().to_dict()}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(OUTPUT_FILE)
    print(f"\n  Saved -> {OUTPUT_FILE}")
    print("\nDone.")


if __name__ == "__main__":
    main()
