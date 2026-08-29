"""
Batch 3 Quantitative Strategy Engines (EQATS Institutional Adaptation)
Adapted from ranjeet867/Metatrader

Provides:
- VWAP Fade Strategy Engine (session-anchored mean reversion)
- Overnight Drift Strategy Engine (overnight equity drift premium)
- Volatility Expansion Breakout Engine (ATR / Keltner range expansion)
- Engulfing at Extreme Engine (extreme high/low candlestick reversals)
- Pivot Reaction Zone Engine (floor pivot support/resistance reaction)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class QuantSignal:
    direction: str  # "BUY", "SELL", "HOLD"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    strategy_name: str
    reason: str


class VWAPFadeStrategy:
    """VWAP Fade Mean Reversion Strategy Engine."""

    def __init__(self, k_entry: float = 1.5, k_stop: float = 2.5):
        self.k_entry = k_entry
        self.k_stop = k_stop

    def evaluate(self, current_price: float, vwap: float, std_dev: float) -> QuantSignal:
        if std_dev <= 0:
            return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "vwap_fade", "Zero std dev")

        upper_bound = vwap + (self.k_entry * std_dev)
        lower_bound = vwap - (self.k_entry * std_dev)

        if current_price < lower_bound:
            stop = vwap - (self.k_stop * std_dev)
            target = vwap
            dev_sigmas = (vwap - current_price) / std_dev
            confidence = min(0.95, 0.5 + (dev_sigmas * 0.1))
            return QuantSignal("BUY", current_price, stop, target, confidence, "vwap_fade", f"Oversold {dev_sigmas:.2f}sigma below VWAP")

        elif current_price > upper_bound:
            stop = vwap + (self.k_stop * std_dev)
            target = vwap
            dev_sigmas = (current_price - vwap) / std_dev
            confidence = min(0.95, 0.5 + (dev_sigmas * 0.1))
            return QuantSignal("SELL", current_price, stop, target, confidence, "vwap_fade", f"Overbought {dev_sigmas:.2f}sigma above VWAP")

        return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "vwap_fade", "Within normal VWAP bands")


class OvernightDriftStrategy:
    """Overnight Equity Drift Strategy Engine."""

    def evaluate(self, current_price: float, atr: float) -> QuantSignal:
        if atr <= 0:
            return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "overnight_drift", "Zero ATR")

        stop = current_price - (3.0 * atr)
        target = current_price + (3.0 * atr)
        return QuantSignal("BUY", current_price, stop, target, 0.70, "overnight_drift", "Overnight drift long bias")


class VolatilityExpansionStrategy:
    """Volatility Expansion Breakout Engine."""

    def evaluate(self, current_price: float, upper_keltner: float, lower_keltner: float, atr: float) -> QuantSignal:
        if atr <= 0:
            return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "vol_expansion", "Zero ATR")

        if current_price > upper_keltner:
            stop = current_price - (1.5 * atr)
            target = current_price + (3.0 * atr)
            return QuantSignal("BUY", current_price, stop, target, 0.80, "vol_expansion", "Breakout above upper Keltner band")
        elif current_price < lower_keltner:
            stop = current_price + (1.5 * atr)
            target = current_price - (3.0 * atr)
            return QuantSignal("SELL", current_price, stop, target, 0.80, "vol_expansion", "Breakout below lower Keltner band")

        return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "vol_expansion", "Consolidating inside bands")


class EngulfingAtExtremeStrategy:
    """Engulfing Candlestick Pattern at Extreme Levels."""

    def evaluate(
        self,
        prev_open: float,
        prev_close: float,
        curr_open: float,
        curr_close: float,
        recent_high: float,
        recent_low: float,
        atr: float,
    ) -> QuantSignal:
        if atr <= 0:
            return QuantSignal("HOLD", curr_close, 0.0, 0.0, 0.0, "engulfing_extreme", "Zero ATR")

        # Bullish Engulfing at Recent Low
        if prev_close < prev_open and curr_close > curr_open:
            if curr_open <= prev_close and curr_close >= prev_open and curr_close <= (recent_low + 2.0 * atr):
                stop = curr_close - (1.5 * atr)
                target = curr_close + (3.0 * atr)
                return QuantSignal("BUY", curr_close, stop, target, 0.82, "engulfing_extreme", "Bullish engulfing at extreme low")

        # Bearish Engulfing at Recent High
        if prev_close > prev_open and curr_close < curr_open:
            if curr_open >= prev_close and curr_close <= prev_open and curr_close >= (recent_high - 2.0 * atr):
                stop = curr_close + (1.5 * atr)
                target = curr_close - (3.0 * atr)
                return QuantSignal("SELL", curr_close, stop, target, 0.82, "engulfing_extreme", "Bearish engulfing at extreme high")

        return QuantSignal("HOLD", curr_close, 0.0, 0.0, 0.0, "engulfing_extreme", "No extreme engulfing pattern")


class PivotReactionZoneStrategy:
    """Floor Pivot Support/Resistance Reaction Engine."""

    def evaluate(self, current_price: float, pivot: float, r1: float, s1: float, atr: float) -> QuantSignal:
        if atr <= 0:
            return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "pivot_reaction", "Zero ATR")

        # Reversal at S1 Support
        if abs(current_price - s1) <= (0.5 * atr):
            stop = s1 - (1.0 * atr)
            target = pivot
            return QuantSignal("BUY", current_price, stop, target, 0.78, "pivot_reaction", "Bounce off S1 Support Zone")

        # Reversal at R1 Resistance
        if abs(current_price - r1) <= (0.5 * atr):
            stop = r1 + (1.0 * atr)
            target = pivot
            return QuantSignal("SELL", current_price, stop, target, 0.78, "pivot_reaction", "Rejection from R1 Resistance Zone")

        return QuantSignal("HOLD", current_price, 0.0, 0.0, 0.0, "pivot_reaction", "Outside active pivot reaction zones")
