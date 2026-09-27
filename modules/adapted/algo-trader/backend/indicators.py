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
Indicator computation pipeline.

All functions accept a standard OHLCV DataFrame (columns: open, high, low, close, volume).
compute_all(df) is the single entry point — call it to get a fully enriched DataFrame
ready for the regime classifier.
"""

import numpy as np
import pandas as pd

# ── Core indicators ───────────────────────────────────────────────────────────


def vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume Weighted Average Price, reset each calendar day.
    Institutions use this as a benchmark — price above VWAP = bullish bias.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3
    tpv = tp * df["volume"]

    # groupby date resets the cumsum at each new trading day
    date_key = df.index.date
    cum_tpv = tpv.groupby(date_key).cumsum()
    cum_vol = df["volume"].groupby(date_key).cumsum()

    return cum_tpv / cum_vol.replace(0, np.nan)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index — measures trend *strength*, not direction.
    ADX > 25 → trending market.
    ADX < 18 → sideways / no trend.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # Raw directional movement
    dm_plus = (high - prev_high).clip(lower=0)
    dm_minus = (prev_low - low).clip(lower=0)

    # When both are positive, only the larger one counts
    both_positive = (dm_plus > 0) & (dm_minus > 0)
    dm_plus = dm_plus.where(~both_positive | (dm_plus >= dm_minus), 0)
    dm_minus = dm_minus.where(~both_positive | (dm_minus > dm_plus), 0)

    # True range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder smoothing (equivalent to EMA with alpha = 1/period)
    smooth = {"alpha": 1 / period, "adjust": False}
    atr_s = tr.ewm(**smooth).mean()
    di_pos = 100 * dm_plus.ewm(**smooth).mean() / atr_s.replace(0, np.nan)
    di_neg = 100 * dm_minus.ewm(**smooth).mean() / atr_s.replace(0, np.nan)

    dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return dx.ewm(**smooth).mean()


def ema_slope(series: pd.Series, period: int = 20, lookback: int = 5) -> pd.Series:
    """
    Normalized slope of EMA over the last `lookback` bars.
    Positive = price trending up, negative = down.
    Values are % change so they're comparable across stocks.
    """
    e = series.ewm(span=period, adjust=False).mean()
    return (e - e.shift(lookback)) / e.shift(lookback)


def vwap_crossings(close: pd.Series, vwap_s: pd.Series, window: int = 30) -> pd.Series:
    """
    Count of VWAP crossings in the last `window` bars.
    High count → price oscillating around VWAP → sideways regime signal.
    """
    above = (close > vwap_s).astype(int)
    crosses = above.diff().abs()  # 1 at each crossing, 0 otherwise
    return crosses.rolling(window, min_periods=1).sum()


def atr_ratio(df: pd.DataFrame, period: int = 14, lookback: int = 5) -> pd.Series:
    """
    Current ATR divided by ATR `lookback` bars ago.
    Ratio > 1.2 → volatility expanding → high-volatility regime signal.
    """
    from engine import atr as _atr

    current = _atr(df, period)
    past = current.shift(lookback)
    return current / past.replace(0, np.nan)


def trend_structure(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    Linear regression slope of highs and lows over `lookback` bars.
    Returns:  1 if both sloping up (HH/HL — uptrend structure)
             -1 if both sloping down (LH/LL — downtrend)
              0 if mixed

    Uses polyfit slope instead of a loop — vectorized via rolling apply.
    """
    x = np.arange(lookback)

    def _slope(y):
        return np.polyfit(x, y, 1)[0]

    high_slope = df["high"].rolling(lookback).apply(_slope, raw=True)
    low_slope = df["low"].rolling(lookback).apply(_slope, raw=True)

    result = pd.Series(0, index=df.index, dtype=int)
    result[(high_slope > 0) & (low_slope > 0)] = 1
    result[(high_slope < 0) & (low_slope < 0)] = -1
    return result


# ── Main pipeline ─────────────────────────────────────────────────────────────


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich an OHLCV DataFrame with all indicators needed by the regime classifier.

    Added columns:
        vwap          — daily reset VWAP
        atr           — Average True Range (14)
        ema20         — 20-period EMA
        ema_slope     — normalized EMA slope over last 5 bars
        adx           — trend strength (14)
        vwap_crosses  — VWAP crossing count in last 30 bars
        atr_ratio     — current ATR vs 5 bars ago (volatility expansion)
        trend_struct  — {1, 0, -1} HH/HL structure over last 10 bars
    """
    from engine import atr as _atr
    from engine import ema

    out = df.copy()
    out["vwap"] = vwap(out)
    out["atr"] = _atr(out, 14)
    out["ema20"] = ema(out["close"], 20)
    out["ema_slope"] = ema_slope(out["close"], period=20, lookback=5)
    out["adx"] = adx(out, 14)
    out["vwap_crosses"] = vwap_crossings(out["close"], out["vwap"], window=30)
    out["atr_ratio"] = atr_ratio(out, period=14, lookback=5)
    out["trend_struct"] = trend_structure(out, lookback=10)
    # EWM-based volume baseline — valid from bar 1 once warm-up data is prepended
    out["vol_avg"] = out["volume"].ewm(span=20, adjust=False).mean()

    return out.dropna()
