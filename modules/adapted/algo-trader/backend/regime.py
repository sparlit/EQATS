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
Regime classifier — detects market condition from the first 30 minutes of data.

Three regimes:
    trending     — ADX strong, directional price movement, clear EMA slope
    sideways     — low ADX, price oscillating around VWAP, no direction
    high_vol     — ATR expanding rapidly, large candles, unstable action

Call classify(df_window) with the first 30-min slice of enriched bars.
Returns probabilities so callers can see how confident the classification is.
"""

import numpy as np
import pandas as pd

# Thresholds — tuned for NSE 5m bars
_ADX_TREND = 25.0  # ADX above this = trending
_ADX_SIDE = 18.0  # ADX below this = sideways
_SLOPE_MIN = 0.001  # EMA slope > this = directional
_ATR_RATIO = 1.20  # ATR expansion ratio > this = volatile
_VWAP_CROSS = 4  # crossings in 30 min > this = choppy


def classify(df_window: pd.DataFrame) -> dict:
    """
    Classify the market regime from an enriched DataFrame window.

    Expects columns from indicators.compute_all():
        adx, ema_slope, vwap_crosses, atr_ratio, trend_struct, close, vwap

    Returns:
        {
            "regime":       "trending" | "sideways" | "high_vol",
            "trend_prob":   float,
            "sideways_prob":float,
            "highvol_prob": float,
            "adx":          float,   # last bar values for logging
            "ema_slope":    float,
        }
    """
    if df_window.empty:
        return _no_data_result()

    # Use the last bar for point-in-time values
    last = df_window.iloc[-1]
    adx_val = float(last["adx"])
    slope = float(last["ema_slope"])
    crosses = float(last["vwap_crosses"])
    atr_r = float(last["atr_ratio"])
    struct = float(last["trend_struct"])

    # Price distance from VWAP (normalized by ATR)
    vwap_dist = abs(float(last["close"]) - float(last["vwap"])) / max(float(last["atr"]), 0.01)

    # ── Score each regime (0–1 per signal, then weighted) ────────────────────

    # Trend: high ADX, clear EMA slope, price away from VWAP, HH/HL structure
    trend_score = _score(
        [
            (adx_val > _ADX_TREND, 0.35),
            (abs(slope) > _SLOPE_MIN, 0.25),
            (vwap_dist > 1.0, 0.20),
            (struct != 0, 0.20),
        ]
    )

    # Sideways: low ADX, many VWAP crossings, flat slope, price hugging VWAP
    side_score = _score(
        [
            (adx_val < _ADX_SIDE, 0.35),
            (crosses > _VWAP_CROSS, 0.30),
            (abs(slope) < _SLOPE_MIN / 2, 0.20),
            (vwap_dist < 0.5, 0.15),
        ]
    )

    # High volatility: ATR expanding, big candles vs recent average
    vol_score = _score(
        [
            (atr_r > _ATR_RATIO, 0.50),
            (atr_r > 1.5, 0.30),  # extra weight for extreme expansion
            (crosses > _VWAP_CROSS * 2, 0.20),  # chaotic crossings also signal vol
        ]
    )

    # Normalize to probabilities
    total = trend_score + side_score + vol_score or 1.0
    tp = round(trend_score / total, 3)
    sp = round(side_score / total, 3)
    vp = round(vol_score / total, 3)

    # Dominant regime = highest probability
    regime = max(
        [("trending", tp), ("sideways", sp), ("high_vol", vp)],
        key=lambda x: x[1],
    )[0]

    return {
        "regime": regime,
        "trend_prob": tp,
        "sideways_prob": sp,
        "highvol_prob": vp,
        "adx": round(adx_val, 2),
        "ema_slope": round(slope, 5),
    }


def _score(signals: list[tuple[bool, float]]) -> float:
    """Sum weights for conditions that are True."""
    return sum(weight for condition, weight in signals if condition)


def _no_data_result() -> dict:
    return {
        "regime": "sideways",  # conservative default: don't trend-follow without data
        "trend_prob": 0.0,
        "sideways_prob": 1.0,
        "highvol_prob": 0.0,
        "adx": 0.0,
        "ema_slope": 0.0,
    }
