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
Stage 3 — Metric: EMA Distance

Computes 20-day and 50-day EMAs of close as of T, and the percentage
distance of close from each EMA.

  EMA_20      = 20-day EMA of close as of T  [ewm(span=20, adjust=False)]
  EMA_50      = 50-day EMA of close as of T  [ewm(span=50, adjust=False)]
  dist_ema_20 = (close_T - EMA_20) / EMA_20 * 100
  dist_ema_50 = (close_T - EMA_50) / EMA_50 * 100

Interpretation (dist_ema_50):
  > +20%     : Medium-term stretched — high reversion risk
  +8% to +20%: Extended but not extreme
  0% to +8%  : Healthy — price hugging EMA, controlled trend
  Negative   : Price below EMA — weakening (G6 mostly filters these)

Combined signals:
  RSI >70 + dist_ema_50 >20% = doubly extended, avoid new entry
  RSI >70 + dist_ema_50 <8%  = strong but not stretched = best continuation setup

Inputs:
  prices : full prices.parquet dataframe (all dates up to and including T)
  T      : as-of date (pd.Timestamp) — EMA computed using all rows <= T

Returns:
  DataFrame with columns [symbol, ema_20, ema_50, dist_ema_20, dist_ema_50]
  Symbols with fewer than 20 price observations return NaN for ema_20/dist_ema_20;
  fewer than 50 return NaN for ema_50/dist_ema_50.
"""

import numpy as np
import pandas as pd


def _compute_ema_row(close: pd.Series, span: int) -> tuple:
    """
    Compute EMA(span) for a single symbol's close series.
    Returns (ema_value, close_T) where ema_value is the last EMA value,
    or (NaN, NaN) if insufficient data.
    """
    close = close.dropna().reset_index(drop=True)
    if len(close) < span:
        return np.nan, np.nan
    ema = close.ewm(span=span, adjust=False).mean()
    return round(ema.iloc[-1], 4), close.iloc[-1]


def compute(prices: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    Compute EMA-20, EMA-50, dist_ema_20, dist_ema_50 for every symbol, as of T.

    Parameters
    ----------
    prices : DataFrame with columns [symbol, date, close, ...]
    T      : latest date to include (inclusive)

    Returns
    -------
    DataFrame with columns [symbol, ema_20, ema_50, dist_ema_20, dist_ema_50]
    """
    df = prices[prices["date"] <= T][["symbol", "date", "close"]].copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    records = []
    for symbol, grp in df.groupby("symbol", sort=False):
        close = grp["close"].reset_index(drop=True)
        ema20, close_t = _compute_ema_row(close, 20)
        ema50, _ = _compute_ema_row(close, 50)

        dist20 = (
            round((close_t - ema20) / ema20 * 100, 4)
            if not (np.isnan(ema20) or ema20 == 0)
            else np.nan
        )
        dist50 = (
            round((close_t - ema50) / ema50 * 100, 4)
            if not (np.isnan(ema50) or ema50 == 0)
            else np.nan
        )

        records.append(
            {
                "symbol": symbol,
                "ema_20": ema20,
                "ema_50": ema50,
                "dist_ema_20": dist20,
                "dist_ema_50": dist50,
            }
        )

    results = pd.DataFrame(records)

    for col, min_obs in [("ema_20", 20), ("ema_50", 50)]:
        n_null = results[col].isnull().sum()
        if n_null > 0:
            print(f"WARNING: {n_null} symbol(s) have NaN {col} (< {min_obs} price rows)")

    print(f"dist_ema_20: [{results['dist_ema_20'].min():.2f}, {results['dist_ema_20'].max():.2f}]")
    print(f"dist_ema_50: [{results['dist_ema_50'].min():.2f}, {results['dist_ema_50'].max():.2f}]")

    return results[["symbol", "ema_20", "ema_50", "dist_ema_20", "dist_ema_50"]]
