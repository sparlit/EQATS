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
Stage 3 — Metric: Stochastic RSI (%K and %D)

Computes the Stochastic RSI oscillator for each stock as of T.

  Step 1: Compute RSI_14 as a rolling series (not just the latest value).
          Uses Wilder's smoothing (alpha = 1/14), same as rsi.py.
  Step 2: Over the last 14 RSI values:
            StochRSI = (RSI_14 - min(RSI_14, 14)) / (max(RSI_14, 14) - min(RSI_14, 14))
          If max == min (flat RSI), StochRSI = 0.
  Step 3: %K = 3-period SMA of StochRSI   (smoothed line)
          %D = 3-period SMA of %K          (signal line)
  Step 4: Take the latest %K and %D as of T.

Minimum price history required:
  14 (RSI seed) + 14 (StochRSI window) + 3 (%K smooth) + 3 (%D smooth) − overlaps ≈ 34 rows

Interpretation (stoch_rsi_k):
  > 0.80        : RSI near top of recent range — momentum extended
  0.20 – 0.80   : Neutral range
  < 0.20        : RSI near bottom of recent range — momentum reset

Key signals:
  %K crossing above %D from below 0.20          → momentum turning up from oversold (entry signal)
  %K crossing above %D from below 0.20 while
    RSI still 50–65                              → best setup: pullback entry within uptrend
  %K > 0.80 with %D also > 0.80                 → both lines extended, caution on new entries

Inputs:
  prices : full prices.parquet dataframe (all dates up to and including T)
  T      : as-of date (pd.Timestamp)

Returns:
  DataFrame with columns [symbol, stoch_rsi_k, stoch_rsi_d]
  Symbols with insufficient history return NaN.
"""

import numpy as np
import pandas as pd

RSI_PERIOD = 14
STOCH_PERIOD = 14
K_SMOOTH = 3
D_SMOOTH = 3

# Minimum rows needed to produce a valid %D
MIN_ROWS = RSI_PERIOD + STOCH_PERIOD + K_SMOOTH + D_SMOOTH - 2  # conservative floor


def _wilder_rsi_series(close: pd.Series, n: int) -> pd.Series:
    """
    Compute the full Wilder RSI(n) series for a close price series.
    Returns a Series of RSI values (same index as close, NaN for first n rows).
    """
    close = close.reset_index(drop=True)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    rsi_vals = [np.nan] * len(close)

    if len(close) < n + 1:
        return pd.Series(rsi_vals, dtype=float)

    # Seed
    avg_gain = gain.iloc[1 : n + 1].mean()
    avg_loss = loss.iloc[1 : n + 1].mean()

    def _rsi_from_avgs(ag, al):
        if al == 0:
            return 100.0
        return 100 - (100 / (1 + ag / al))

    rsi_vals[n] = _rsi_from_avgs(avg_gain, avg_loss)

    for i in range(n + 1, len(close)):
        avg_gain = (avg_gain * (n - 1) + gain.iloc[i]) / n
        avg_loss = (avg_loss * (n - 1) + loss.iloc[i]) / n
        rsi_vals[i] = _rsi_from_avgs(avg_gain, avg_loss)

    return pd.Series(rsi_vals, dtype=float)


def _compute_stoch_rsi(close: pd.Series) -> tuple:
    """
    Compute %K and %D of StochRSI for a single symbol's close series.
    Returns (k, d) as floats, or (NaN, NaN) if insufficient data.
    """
    close = close.dropna().reset_index(drop=True)

    if len(close) < MIN_ROWS:
        return np.nan, np.nan

    rsi_series = _wilder_rsi_series(close, RSI_PERIOD)
    rsi_valid = rsi_series.dropna()

    if len(rsi_valid) < STOCH_PERIOD + K_SMOOTH + D_SMOOTH - 2:
        return np.nan, np.nan

    # StochRSI over rolling 14-period window of RSI values
    stoch = rsi_valid.rolling(STOCH_PERIOD).apply(
        lambda x: (x[-1] - x.min()) / (x.max() - x.min()) if (x.max() - x.min()) != 0 else 0.0,
        raw=True,
    )

    # %K = 3-SMA of StochRSI
    k_series = stoch.rolling(K_SMOOTH).mean()

    # %D = 3-SMA of %K
    d_series = k_series.rolling(D_SMOOTH).mean()

    k = k_series.dropna().iloc[-1] if k_series.dropna().shape[0] > 0 else np.nan
    d = d_series.dropna().iloc[-1] if d_series.dropna().shape[0] > 0 else np.nan

    return (
        round(float(k), 4) if not np.isnan(k) else np.nan,
        round(float(d), 4) if not np.isnan(d) else np.nan,
    )


def compute(prices: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    Compute StochRSI %K and %D for every symbol in prices, as of T.

    Parameters
    ----------
    prices : DataFrame with columns [symbol, date, close, ...]
    T      : latest date to include (inclusive)

    Returns
    -------
    DataFrame with columns [symbol, stoch_rsi_k, stoch_rsi_d]
    """
    df = prices[prices["date"] <= T][["symbol", "date", "close"]].copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    records = []
    for symbol, grp in df.groupby("symbol", sort=False):
        k, d = _compute_stoch_rsi(grp["close"])
        records.append({"symbol": symbol, "stoch_rsi_k": k, "stoch_rsi_d": d})

    results = pd.DataFrame(records)

    for col in ["stoch_rsi_k", "stoch_rsi_d"]:
        n_null = results[col].isnull().sum()
        if n_null > 0:
            print(f"WARNING: {n_null} symbol(s) have NaN {col} (insufficient price history)")

    valid_k = results["stoch_rsi_k"].dropna()
    if len(valid_k):
        print(f"StochRSI %K: [{valid_k.min():.4f}, {valid_k.max():.4f}]")

    return results[["symbol", "stoch_rsi_k", "stoch_rsi_d"]]
