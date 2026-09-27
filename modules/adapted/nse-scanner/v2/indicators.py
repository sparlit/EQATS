from __future__ import annotations

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


"""Pure, reusable technical indicators for NSE Scanner V2.

These functions contain no database, Telegram or workflow side effects so the
same implementation can be reused by live scanning and future backtests.
"""

import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable


def _series(values: Iterable[float] | pd.Series) -> pd.Series:
    return pd.to_numeric(pd.Series(values, copy=False), errors="coerce").astype(float)


def wma(values: Iterable[float] | pd.Series, length: int) -> pd.Series:
    """Weighted moving average with linearly increasing weights."""
    if length < 1:
        msg = "length must be >= 1"
        raise ValueError(msg)
    s = _series(values)
    weights = np.arange(1, length + 1, dtype=float)
    denominator = weights.sum()
    return s.rolling(length, min_periods=length).apply(
        lambda window: float(np.dot(window, weights) / denominator), raw=True
    )


def hma(values: Iterable[float] | pd.Series, length: int) -> pd.Series:
    """Hull moving average: WMA(2*WMA(n/2)-WMA(n), sqrt(n))."""
    if length < 2:
        msg = "length must be >= 2"
        raise ValueError(msg)
    half = max(1, length // 2)
    root = max(1, int(math.sqrt(length)))
    raw = 2.0 * wma(values, half) - wma(values, length)
    return wma(raw, root)


def true_range(frame: pd.DataFrame) -> pd.Series:
    required = {"high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        msg = f"missing columns: {sorted(missing)}"
        raise ValueError(msg)
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous_close = close.shift(1)
    return pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder ATR using an exponentially smoothed true range."""
    if length < 1:
        msg = "length must be >= 1"
        raise ValueError(msg)
    return true_range(frame).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def atr_percent(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    close = pd.to_numeric(frame["close"], errors="coerce")
    return 100.0 * atr(frame, length) / close.replace(0, np.nan)


def extension_from_hma(frame: pd.DataFrame, hma_length: int = 55, atr_length: int = 14) -> pd.Series:
    """Distance of close above/below HMA expressed in ATR units."""
    close = pd.to_numeric(frame["close"], errors="coerce")
    baseline = hma(close, hma_length)
    volatility = atr(frame, atr_length).replace(0, np.nan)
    return (close - baseline) / volatility


def hybrid_hull(frame: pd.DataFrame, fast: int = 21, slow: int = 55) -> pd.DataFrame:
    """Return fast/slow HMA and a deterministic direction state.

    State is 1 when fast HMA is above slow HMA and rising, -1 when below and
    falling, otherwise 0. This is a trend-permission component, not an entry.
    """
    close = pd.to_numeric(frame["close"], errors="coerce")
    fast_hma = hma(close, fast)
    slow_hma = hma(close, slow)
    rising = fast_hma.diff() > 0
    falling = fast_hma.diff() < 0
    state = pd.Series(0, index=frame.index, dtype="int64")
    state[(fast_hma > slow_hma) & rising] = 1
    state[(fast_hma < slow_hma) & falling] = -1
    return pd.DataFrame(
        {"hma_fast": fast_hma, "hma_slow": slow_hma, "hybrid_hull_state": state},
        index=frame.index,
    )


def kama(values: Iterable[float] | pd.Series, length: int = 30) -> pd.Series:
    """TradingView-compatible Kaufman adaptive moving average."""
    if length < 1:
        msg = "length must be >= 1"
        raise ValueError(msg)
    series = _series(values)
    change = (series - series.shift(length)).abs()
    volatility = series.diff().abs().rolling(length).sum()
    efficiency = (change / volatility.replace(0, np.nan)).fillna(0.0)
    fast, slow = 2.0 / 3.0, 2.0 / (length + 1.0)
    smoothing = (efficiency * (fast - slow) + slow) ** 2
    result = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series):
        result.iloc[0] = series.iloc[0]
    for index in range(1, len(series)):
        result.iloc[index] = result.iloc[index - 1] + smoothing.iloc[index] * (
            series.iloc[index] - result.iloc[index - 1]
        )
    return result


def fixed_hybrid_hull_signals(frame: pd.DataFrame) -> dict[str, float | bool]:
    """Return EOD Hull structure using multi-session persistence.

    KAMA is retained as a diagnostic for backward-compatible reports, but is
    deliberately not used by the selection or readiness gates.
    """
    required = {"trade_date", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        msg = f"missing columns: {sorted(missing)}"
        raise ValueError(msg)
    data = frame.sort_values("trade_date").copy()
    close = pd.to_numeric(data["close"], errors="coerce")
    hull55 = 2.0 * wma(wma(close, 55), 27) - wma(wma(close, 55), 55)
    hma21 = hma(close, 21)
    hma51 = hma(close, 51)
    atr14 = atr(data, 14)
    kama30 = kama(close, 30)
    if len(data) < 56 or pd.isna(hull55.iloc[-1]) or pd.isna(atr14.iloc[-1]):
        return {
            "daily_bullish": False,
            "daily_persistent": False,
            "hull_slope_improving": False,
            "weekly_bullish": False,
            "kama_rising": False,
            "stretched": False,
            "chop": True,
            "trail_stop": 0.0,
            "hull55": 0.0,
            "hma21": 0.0,
            "hma51": 0.0,
            "atr14": 0.0,
            "distance_atr": 0.0,
        }

    last_close = float(close.iloc[-1])
    last_atr = float(atr14.iloc[-1])
    distance_atr = (last_close - float(hull55.iloc[-1])) / last_atr if last_atr > 0 else 0.0
    daily_bullish = bool(
        last_close > float(hull55.iloc[-1]) > float(hull55.iloc[-2]) and float(hma21.iloc[-1]) > float(hma51.iloc[-1])
    )
    above_hull_5 = close.tail(5).reset_index(drop=True) > hull55.tail(5).reset_index(drop=True)
    hull_slopes_5 = hull55.diff().tail(5)
    hull_slope_improving = bool((hull_slopes_5 >= 0).sum() >= 2 and hull55.iloc[-1] >= hull55.iloc[-3])
    hma_aligned = bool(float(hma21.iloc[-1]) > float(hma51.iloc[-1]))
    daily_persistent = bool(above_hull_5.sum() >= 3 and hull_slope_improving and hma_aligned)
    kama_rising = bool(float(kama30.iloc[-1]) > float(kama30.iloc[-2]) and daily_bullish)
    price_band = (close.tail(20).max() - close.tail(20).min()) / max(last_close, 1.0)
    rotation = abs(distance_atr) < 0.4 and abs(float(hull55.iloc[-1] - hull55.iloc[-2])) < last_atr * 0.15
    low_hull_impulse = abs(float(hull55.iloc[-1] - hull55.iloc[-2])) < last_atr * 0.08
    chop = bool((low_hull_impulse and price_band < 0.025) or rotation)

    weekly_close = data.set_index(pd.to_datetime(data["trade_date"]))["close"].resample("W-FRI").last().dropna()
    weekly21, weekly51 = hma(weekly_close, 21), hma(weekly_close, 51)
    weekly_bullish = bool(
        len(weekly_close) >= 52
        and pd.notna(weekly21.iloc[-1])
        and pd.notna(weekly51.iloc[-1])
        and weekly21.iloc[-1] > weekly51.iloc[-1]
        and weekly21.iloc[-1] >= weekly21.iloc[-2]
    )
    return {
        "daily_bullish": daily_bullish,
        "daily_persistent": daily_persistent,
        "hull_above_sessions_5": int(above_hull_5.sum()),
        "hull_slope_improving": hull_slope_improving,
        "weekly_bullish": weekly_bullish,
        "kama_rising": kama_rising,
        "stretched": bool(distance_atr > 1.5),
        "chop": chop,
        "trail_stop": round(float(hull55.iloc[-1]) - 3.5 * last_atr, 2),
        "hull55": round(float(hull55.iloc[-1]), 2),
        "hma21": round(float(hma21.iloc[-1]), 2),
        "hma51": round(float(hma51.iloc[-1]), 2),
        "atr14": round(last_atr, 2),
        "distance_atr": round(distance_atr, 2),
    }


def relative_strength_ratio(stock_close: pd.Series, benchmark_close: pd.Series) -> pd.Series:
    """Price-relative series normalized to 100 at the first common valid point."""
    stock, benchmark = pd.to_numeric(stock_close, errors="coerce").align(
        pd.to_numeric(benchmark_close, errors="coerce"), join="inner"
    )
    ratio = stock / benchmark.replace(0, np.nan)
    valid = ratio.dropna()
    if valid.empty:
        return ratio
    return 100.0 * ratio / valid.iloc[0]


def relative_strength_return(stock_close: pd.Series, benchmark_close: pd.Series, lookback: int = 63) -> pd.Series:
    """Stock return minus benchmark return over a fixed trading-session lookback."""
    if lookback < 1:
        msg = "lookback must be >= 1"
        raise ValueError(msg)
    stock, benchmark = pd.to_numeric(stock_close, errors="coerce").align(
        pd.to_numeric(benchmark_close, errors="coerce"), join="inner"
    )
    return stock.pct_change(lookback) - benchmark.pct_change(lookback)
