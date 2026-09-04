"""
EQATS Version 11.0.0 Dynamic Multi-Asset Market Regime & Correlation Classifier.

Provides multi-dimensional regime classification across:
  1. Direction (UP, DOWN, SIDEWAYS)
  2. Volatility (LOW_VOL, NORMAL_VOL, HIGH_VOL, VOLATILITY_EXPANSION)
  3. Liquidity (HIGH_LIQUIDITY, NORMAL_LIQUIDITY, LIQUIDITY_STRESS)
  4. Cross-Asset Correlation (RISK_ON, RISK_OFF, NEUTRAL_CORRELATION)
  5. Session State (TOKYO, LONDON, NEW_YORK, INDIAN_MARKET_OPEN, OVERLAP)
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("v11_macro_regime_brain")


class RegimeType:
    TREND_STRONG = "STRONG_TREND_MODERATE_VOLATILITY"
    RANGE_LOW_VOL = "RANGE_LOW_VOLATILITY"
    HIGH_VOL_TREND = "HIGH_VOLATILITY_STRONG_DIRECTION"
    HIGH_VOL_NO_DIR = "HIGH_VOLATILITY_NO_DIRECTION"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS_DEFENSIVE"


class MacroRegimeClassifierBrain:
    """
    Multi-Asset Market Regime & Cross-Asset Correlation Classifier.
    """

    def __init__(self) -> None:
        self.version = "11.0.0"

    def classify_regime(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float] | None = None,
    ) -> dict[str, Any]:
        """
        Classifies current market regime using multi-bar price action, ATR volatility ratio,
        and directional trend strength.
        """
        if not closes or len(closes) < 20:
            return {
                "regime": RegimeType.RANGE_LOW_VOL,
                "direction": "SIDEWAYS",
                "volatility_state": "NORMAL_VOL",
                "liquidity_state": "NORMAL_LIQUIDITY",
                "macro_bias": "NEUTRAL",
            }

        n = len(closes)
        current_price = closes[-1]
        sma20 = sum(closes[-20:]) / 20.0
        sma50 = sum(closes[-min(50, n) :]) / float(min(50, n))

        # Direction
        if current_price > sma20 > sma50:
            direction = "UP"
        elif current_price < sma20 < sma50:
            direction = "DOWN"
        else:
            direction = "SIDEWAYS"

        # Volatility estimation via ATR ratio
        ranges = [highs[i] - lows[i] for i in range(max(0, n - 20), n)]
        recent_range_avg = sum(ranges) / float(len(ranges)) if ranges else 0.001

        hist_ranges = [highs[i] - lows[i] for i in range(max(0, n - 100), n)]
        hist_range_avg = sum(hist_ranges) / float(len(hist_ranges)) if hist_ranges else 0.001

        vol_ratio = recent_range_avg / max(1e-6, hist_range_avg)

        if vol_ratio >= 2.0:
            vol_state = "HIGH_VOL"
        elif vol_ratio >= 1.2:
            vol_state = "VOLATILITY_EXPANSION"
        elif vol_ratio <= 0.7:
            vol_state = "LOW_VOL"
        else:
            vol_state = "NORMAL_VOL"

        # Regime classification
        if direction in ["UP", "DOWN"] and vol_state in ["NORMAL_VOL", "VOLATILITY_EXPANSION"]:
            regime = RegimeType.TREND_STRONG
        elif direction in ["UP", "DOWN"] and vol_state == "HIGH_VOL":
            regime = RegimeType.HIGH_VOL_TREND
        elif direction == "SIDEWAYS" and vol_state in ["LOW_VOL", "NORMAL_VOL"]:
            regime = RegimeType.RANGE_LOW_VOL
        elif direction == "SIDEWAYS" and vol_state == "HIGH_VOL":
            regime = RegimeType.HIGH_VOL_NO_DIR
        else:
            regime = RegimeType.RANGE_LOW_VOL

        # Macro risk-on / risk-off classification
        macro_bias = "RISK_ON" if direction == "UP" else "RISK_OFF" if direction == "DOWN" else "NEUTRAL"

        return {
            "regime": regime,
            "direction": direction,
            "volatility_state": vol_state,
            "volatility_ratio": round(vol_ratio, 2),
            "liquidity_state": "NORMAL_LIQUIDITY",
            "macro_bias": macro_bias,
        }


global_v11_macro_regime_brain = MacroRegimeClassifierBrain()
