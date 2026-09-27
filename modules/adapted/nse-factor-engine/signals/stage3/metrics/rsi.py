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
Stage 3 — Metric: RSI (Wilder)

Computes Wilder's Relative Strength Index for each stock as of T.

  RS      = Wilder smoothed avg gain / Wilder smoothed avg loss over N periods
  RSI     = 100 - (100 / (1 + RS))

Implementation follows Wilder's original smoothing (equivalent to EMA with
alpha = 1/N), NOT a simple rolling average. This matches the standard
TA-Lib / TradingView definition.

Steps:
  1. Compute daily price changes from close prices.
  2. Separate gains (positive changes) and losses (absolute negative changes).
  3. Seed the first avg_gain / avg_loss as a simple mean over the first N periods.
  4. Apply Wilder smoothing for all subsequent periods:
       avg_gain[t] = (avg_gain[t-1] * (N-1) + gain[t]) / N
       avg_loss[t] = (avg_loss[t-1] * (N-1) + loss[t]) / N
  5. RS  = avg_gain / avg_loss  (avg_loss == 0 -> RS = inf -> RSI = 100)
  6. RSI = 100 - (100 / (1 + RS))

Inputs:
  prices : full prices.parquet dataframe (all dates up to and including T)
  T      : as-of date (pd.Timestamp) — RSI computed using all rows <= T

Returns:
  dataframe with columns [symbol, rsi_14, rsi_7]
  Symbols with fewer than N+1 price observations return NaN for that period.
"""

import numpy as np
import pandas as pd


def _wilder_rsi(close: pd.Series, n: int) -> float:
    """
    Compute RSI for a single symbol's close price series.
    Returns the most recent RSI value as a float, or NaN if insufficient data.
    """
    close = close.dropna().reset_index(drop=True)
    if len(close) < n + 1:
        return np.nan

    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Seed: simple mean of first N periods
    avg_gain = gain.iloc[:n].mean()
    avg_loss = loss.iloc[:n].mean()

    # Wilder smoothing for remaining periods
    for i in range(n, len(gain)):
        avg_gain = (avg_gain * (n - 1) + gain.iloc[i]) / n
        avg_loss = (avg_loss * (n - 1) + loss.iloc[i]) / n

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 4)


def compute(prices: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    Compute Wilder RSI-14 and RSI-7 for every symbol in prices, as of T.

    Parameters
    ----------
    prices : DataFrame with columns [symbol, date, close, ...]
    T      : latest date to include (inclusive)

    Returns
    -------
    DataFrame with columns [symbol, rsi_14, rsi_7]
    """
    df = prices[prices["date"] <= T][["symbol", "date", "close"]].copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    rsi14 = (
        df.groupby("symbol")["close"]
        .apply(lambda s: _wilder_rsi(s, 14))
        .reset_index()
        .rename(columns={"close": "rsi_14"})
    )
    rsi7 = (
        df.groupby("symbol")["close"]
        .apply(lambda s: _wilder_rsi(s, 7))
        .reset_index()
        .rename(columns={"close": "rsi_7"})
    )

    results = rsi14.merge(rsi7, on="symbol", how="left")

    for col, period in [("rsi_14", 14), ("rsi_7", 7)]:
        n_null = results[col].isnull().sum()
        if n_null > 0:
            print(f"WARNING: {n_null} symbol(s) have NaN {col} (< {period + 1} price rows)")

    print(f"RSI-14: [{results['rsi_14'].min():.2f}, {results['rsi_14'].max():.2f}]")
    print(f"RSI-7 : [{results['rsi_7'].min():.2f}, {results['rsi_7'].max():.2f}]")

    return results[["symbol", "rsi_14", "rsi_7"]]
