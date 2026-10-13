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
universe.py
===========
Shared universe construction utility for all factor scripts.

Expects prices_hmm_daily.parquet in LONG format:
    symbol | date | open | high | low | close | volume

Applies two filters at each month T:
  1. Point-in-time Nifty 500 membership (from constituent CSV)
  2. ADTV filter — average daily traded value (price x volume)
     over past 63 trading days (~3 months) >= threshold

ADTV threshold is time-varying (anchored to market size):
  pre-2018        : 10cr
  2018 to 2021    : 20cr
  2022 onwards    : 30cr

Usage
-----
from factors.universe import build_universe_lookup, get_clean_universe, load_prices_long

universe_df = build_universe_lookup(CONSTITUENT_CSV)
prices_long = load_prices_long(PRICE_FILE)

# At each month T:
universe = get_clean_universe(
    date        = date,
    prices_long = prices_long,
    universe_df = universe_df,
    sym_map     = sym_map,
)
"""

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CRORE = 1e7  # 1 crore = 10 million


def get_adtv_threshold(date: pd.Timestamp) -> float:
    year = date.year
    if year < 2018:
        return 10.0
    elif year <= 2021:
        return 20.0
    else:
        return 30.0


# ---------------------------------------------------------------------------
# Load long-format prices
# ---------------------------------------------------------------------------
def load_prices_long(price_file: Path) -> pd.DataFrame:
    """
    Load prices_hmm_daily.parquet (long format) and return a clean DataFrame.
    Columns: symbol, date, open, high, low, close, volume
    date is parsed to datetime.
    """
    df = pd.read_parquet(price_file)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Step 1 — Build point-in-time universe lookup
# ---------------------------------------------------------------------------
def build_universe_lookup(csv_file: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_file)
    df["effective_date"] = pd.to_datetime(df["effective_date"])
    df = df.sort_values("effective_date").reset_index(drop=True)
    df["symbols_list"] = df["symbols"].apply(
        lambda s: [x.strip() for x in str(s).split(",") if x.strip()]
    )
    return df[["effective_date", "symbols_list"]]


def get_pit_universe(date: pd.Timestamp, universe_df: pd.DataFrame) -> list:
    valid = universe_df[universe_df["effective_date"] <= date]
    if valid.empty:
        return []
    return valid.iloc[-1]["symbols_list"]


# ---------------------------------------------------------------------------
# Step 2 — ADTV filter (long format)
# ---------------------------------------------------------------------------
def compute_adtv(
    date: pd.Timestamp,
    symbols: list,
    prices_long: pd.DataFrame,
    sym_map: dict,
    adtv_days: int = 63,
) -> pd.Series:
    """
    Compute average daily traded value (price x volume) for each stock
    over the past adtv_days trading days up to and including date.
    Works from long-format prices DataFrame.

    Returns
    -------
    pd.Series — ADTV in crore, indexed by symbol
    """
    # All trading dates up to date
    all_dates = prices_long["date"].unique()
    all_dates = np.sort(all_dates[all_dates <= np.datetime64(date)])
    window_dates = all_dates[-adtv_days:] if len(all_dates) >= adtv_days else all_dates

    if len(window_dates) == 0:
        return pd.Series(dtype=float)

    # Filter to window
    window_df = prices_long[prices_long["date"].isin(window_dates)]

    adtv = {}
    for sym in symbols:
        col = sym_map.get(sym, sym)
        sym_df = window_df[window_df["symbol"] == col][["date", "close", "volume"]].dropna()

        if len(sym_df) < 10:
            continue

        dtv = sym_df["close"] * sym_df["volume"]
        adtv_val = dtv.mean() / CRORE

        if pd.notna(adtv_val) and adtv_val > 0:
            adtv[sym] = adtv_val

    return pd.Series(adtv)


# ---------------------------------------------------------------------------
# Step 3 — Combined clean universe
# ---------------------------------------------------------------------------
def get_clean_universe(
    date: pd.Timestamp,
    prices_long: pd.DataFrame,
    universe_df: pd.DataFrame,
    sym_map: dict,
    adtv_crore: float = None,
    adtv_days: int = 63,
) -> list:
    """
    Get clean universe at month-end date T.

    Applies:
      1. Point-in-time Nifty 500 membership
      2. ADTV >= threshold (time-varying by default, or fixed if passed)
      3. Must have price data (non-NaN close) at or before date T

    Returns
    -------
    list of ticker symbols passing all filters
    """
    # 1. Point-in-time membership
    pit = get_pit_universe(date, universe_df)
    if not pit:
        return []

    # 2. Determine ADTV threshold
    threshold = adtv_crore if adtv_crore is not None else get_adtv_threshold(date)

    # 3. ADTV filter
    adtv = compute_adtv(date, pit, prices_long, sym_map, adtv_days)
    adtv_pass = adtv[adtv >= threshold].index.tolist()

    # 4. Must have a valid close price at or before date T
    recent = prices_long[prices_long["date"] <= date]
    clean = []
    for sym in adtv_pass:
        col = sym_map.get(sym, sym)
        sym_px = recent[recent["symbol"] == col]["close"].dropna()
        if not sym_px.empty and sym_px.iloc[-1] > 0:
            clean.append(sym)

    return clean


# ---------------------------------------------------------------------------
# Helper — build wide monthly close from long format (used by factor scripts)
# ---------------------------------------------------------------------------
def build_monthly_close(prices_long: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot long-format daily prices to wide monthly close.
    Index: month-end dates. Columns: symbols.
    """
    daily_wide = prices_long.pivot(index="date", columns="symbol", values="close")
    daily_wide.index = pd.to_datetime(daily_wide.index)
    daily_wide.columns.name = None
    monthly = daily_wide.resample("ME").last()
    return monthly
