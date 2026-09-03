"""
Quantitative Market Analysis Strategy Engine (QMA).
Provides Murphy Failure Swing & RSI Divergence Strategy,
TTM Squeeze Momentum Indicator, and Session Hour Almanac Filter.
"""

import logging
import math
from collections.abc import Sequence
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
logger = logging.getLogger("QMAQuantStrategy")


def detect_rsi_failure_swing(rsi_series: Sequence[float], oversold: float = 35.0, overbought: float = 65.0) -> str:
    """
    Detects Murphy RSI Failure Swing (W-bottom oversold or M-top overbought reversal).
    """
    if len(rsi_series) < 6:
        return "NEUTRAL"
    r = rsi_series[-6:]
    if r[0] < oversold and r[1] > oversold and (r[2] < r[1]) and (r[2] > r[0]) and (r[3] > r[1]):
        return "BUY"
    if r[0] > overbought and r[1] < overbought and (r[2] > r[1]) and (r[2] < r[0]) and (r[3] < r[1]):
        return "SELL"
    return "NEUTRAL"


def calculate_ttm_squeeze(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    bb_period: int = 20,
    kc_period: int = 20,
    kc_mult: float = 1.5,
) -> dict[str, Any]:
    """
    Computes TTM Squeeze Indicator (Bollinger Bands inside Keltner Channels = Squeeze On).
    Returns squeeze state and momentum histogram value.
    """
    if len(closes) < max(bb_period, kc_period):
        return {"squeeze_on": False, "momentum": 0.0, "signal": "NEUTRAL"}
    c = closes[-bb_period:]
    h = highs[-kc_period:]
    l = lows[-kc_period:]
    sma = sum(c) / len(c)
    variance = sum((x - sma) ** 2 for x in c) / len(c)
    std = math.sqrt(variance)
    bb_upper = sma + 2.0 * std
    bb_lower = sma - 2.0 * std
    atr = sum(h[j] - l[j] for j in range(len(h))) / len(h)
    kc_upper = sma + kc_mult * atr
    kc_lower = sma - kc_mult * atr
    squeeze_on = bb_upper < kc_upper and bb_lower > kc_lower
    mom = closes[-1] - sma
    prev_mom = closes[-2] - sma if len(closes) >= 2 else mom
    signal = "NEUTRAL"
    if not squeeze_on and mom > 0 and (mom > prev_mom):
        signal = "BUY"
    elif not squeeze_on and mom < 0 and (mom < prev_mom):
        signal = "SELL"
    return {"squeeze_on": squeeze_on, "momentum": round(mom, 5), "signal": signal}


class QMAQuantStrategy:
    """
    Murphy Failure Swing + TTM Squeeze + Almanac Session Filter Strategy Engine.
    """

    def evaluate_qma_setup(
        self,
        symbol: str,
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        rsi_val: float,
        utc_hour: int = 14,
    ) -> dict[str, Any]:
        blocked_hours = {13, 14, 15}
        if utc_hour in blocked_hours:
            return {"decision": "HOLD", "reason": f"Almanac Session Filter: Hour {utc_hour} UTC blocked"}
        fail_swing = detect_rsi_failure_swing(closes)
        squeeze = calculate_ttm_squeeze(closes, highs, lows)
        decision = "HOLD"
        confidence = 0.5
        if fail_swing == "BUY" or squeeze["signal"] == "BUY":
            decision = "BUY"
            confidence = 0.8 if fail_swing == "BUY" and squeeze["signal"] == "BUY" else 0.65
        elif fail_swing == "SELL" or squeeze["signal"] == "SELL":
            decision = "SELL"
            confidence = 0.8 if fail_swing == "SELL" and squeeze["signal"] == "SELL" else 0.65
        return {
            "symbol": symbol,
            "decision": decision,
            "confidence": confidence,
            "failure_swing": fail_swing,
            "ttm_squeeze_on": squeeze["squeeze_on"],
            "squeeze_momentum": squeeze["momentum"],
        }
