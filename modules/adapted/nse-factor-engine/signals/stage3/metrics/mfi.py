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
Stage 3 — Metric: Money Flow Index (MFI-14)

Computes the 14-period Money Flow Index for each stock as of T.

  Typical Price (TP)    = (High + Low + Close) / 3
  Raw Money Flow        = TP × Volume
  Positive Money Flow   = sum(Raw MF) on days where TP > prev TP, over 14 periods
  Negative Money Flow   = sum(Raw MF) on days where TP <= prev TP, over 14 periods
  Money Flow Ratio      = Positive MF / Negative MF
  MFI_14                = 100 - (100 / (1 + Money Flow Ratio))

Rolling 14-period window ending at T. Last value only is returned.
If Negative MF == 0 for the window, MFI is set to 100.

Interpretation:
  > 80        : Overbought with volume — institutions selling into strength
  50–80 rising: Healthy accumulation
  < 20        : Oversold with volume — capitulation

Combined with RSI:
  RSI >70, MFI >70 : Price rise confirmed by volume → continuation likely
  RSI >70, MFI <50 : Rising on weak volume → suspect, likely to fade
  RSI <40, MFI >50 : Price weak but volume positive → reversal building

Triple confirmation (highest conviction):
  RSI >70 + MFI >70 + dist_ema_50 <10% = best continuation setup in G6_C6

Inputs:
  prices : full prices.parquet dataframe (all dates up to and including T)
           Must contain columns: high, low, close, volume
  T      : as-of date (pd.Timestamp)

Returns:
  DataFrame with columns [symbol, mfi_14]
  Symbols with fewer than 15 price observations return NaN.
"""

import numpy as np
import pandas as pd

MFI_PERIOD = 14


def _compute_mfi(grp: pd.DataFrame, n: int) -> float:
    """
    Compute MFI(n) for a single symbol's OHLCV group.
    Returns the most recent MFI value as float, or NaN if insufficient data.
    """
    grp = grp.dropna(subset=["high", "low", "close", "volume"]).reset_index(drop=True)
    if len(grp) < n + 1:
        return np.nan

    tp = (grp["high"] + grp["low"] + grp["close"]) / 3
    raw_mf = tp * grp["volume"]

    # Need n+1 rows to get n TP-vs-prev comparisons
    tp_tail = tp.iloc[-(n + 1) :].reset_index(drop=True)
    raw_mf_tail = raw_mf.iloc[-(n + 1) :].reset_index(drop=True)

    pos_mf = 0.0
    neg_mf = 0.0
    for i in range(1, n + 1):
        if tp_tail.iloc[i] > tp_tail.iloc[i - 1]:
            pos_mf += raw_mf_tail.iloc[i]
        else:
            neg_mf += raw_mf_tail.iloc[i]

    if neg_mf == 0:
        return 100.0

    mfr = pos_mf / neg_mf
    mfi = 100 - (100 / (1 + mfr))
    return round(mfi, 4)


def compute(prices: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    Compute MFI-14 for every symbol in prices, as of T.

    Parameters
    ----------
    prices : DataFrame with columns [symbol, date, high, low, close, volume]
    T      : latest date to include (inclusive)

    Returns
    -------
    DataFrame with columns [symbol, mfi_14]
    """
    needed = ["symbol", "date", "high", "low", "close", "volume"]
    df = prices[prices["date"] <= T][needed].copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    results = (
        df.groupby("symbol", sort=False)
        .apply(lambda g: _compute_mfi(g, MFI_PERIOD))
        .reset_index()
        .rename(columns={0: "mfi_14"})
    )

    n_null = results["mfi_14"].isnull().sum()
    if n_null > 0:
        print(
            f"WARNING: {n_null} symbol(s) have NaN mfi_14 (< {MFI_PERIOD + 1} price rows or missing OHLCV)"
        )

    valid = results["mfi_14"].dropna()
    if len(valid):
        print(f"MFI-14: [{valid.min():.2f}, {valid.max():.2f}]")

    return results[["symbol", "mfi_14"]]
