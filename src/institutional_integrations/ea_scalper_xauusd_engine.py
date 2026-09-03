"""
EA SCALPER XAUUSD Institutional Engine Core.
Provides AMD (Accumulation, Manipulation, Distribution) Cycle Tracker,
Footprint & Volume Delta POC Analyzer, Gap Cooldown Guard,
and Apex/FTMO Peak Drawdown Tracker.
"""

import logging
import math
from collections.abc import Sequence
from typing import Any, Dict, List, Optional

logger = logging.getLogger("EAScalperXAUUSD")


class AMDCycleTracker:
    """
    Accumulation, Manipulation, Distribution (AMD) Wyckoff Power of 3 Cycle Tracker.
    """

    def detect_amd_phase(
        self, closes: Sequence[float], highs: Sequence[float], lows: Sequence[float], utc_hour: int,
    ) -> dict[str, Any]:
        if len(closes) < 20:
            return {"phase": "ACCUMULATION", "manipulation_detected": False}
        recent_high = max(highs[-20:-2])
        recent_low = min(lows[-20:-2])
        curr_high = highs[-1]
        curr_low = lows[-1]
        curr_close = closes[-1]
        manipulation_high_sweep = curr_high > recent_high and curr_close < recent_high
        manipulation_low_sweep = curr_low < recent_low and curr_close > recent_low
        if manipulation_high_sweep:
            return {"phase": "MANIPULATION", "bias": "SELL", "manipulation_detected": True, "sweep_type": "HIGH_SWEEP"}
        if manipulation_low_sweep:
            return {"phase": "MANIPULATION", "bias": "BUY", "manipulation_detected": True, "sweep_type": "LOW_SWEEP"}
        if 12 <= utc_hour <= 18:
            return {"phase": "DISTRIBUTION", "bias": "TREND_CONTINUATION", "manipulation_detected": False}
        return {"phase": "ACCUMULATION", "bias": "RANGE", "manipulation_detected": False}


class FootprintPocAnalyzer:
    """
    Footprint Point of Control (POC) & Delta Imbalance Analyzer.
    """

    def analyze_footprint(
        self, buy_volume: float, sell_volume: float, poc_price: float, current_price: float,
    ) -> dict[str, Any]:
        tot_vol = buy_volume + sell_volume
        delta = buy_volume - sell_volume
        delta_pct = delta / tot_vol if tot_vol > 0 else 0.0
        is_buyer_imbalance = delta_pct > 0.3
        is_seller_imbalance = delta_pct < -0.3
        above_poc = current_price >= poc_price
        bias = "NEUTRAL"
        if is_buyer_imbalance and above_poc:
            bias = "BULLISH_POC_SUPPORT"
        elif is_seller_imbalance and (not above_poc):
            bias = "BEARISH_POC_RESISTANCE"
        return {
            "total_volume": tot_vol,
            "delta": delta,
            "delta_pct": round(delta_pct, 4),
            "poc_price": poc_price,
            "bias": bias,
        }


class MarketGapCooldownGuard:
    """
    Market Gap & Weekend Slippage Cooldown Guard.
    """

    def __init__(self, cooldown_bars_after_gap: int = 3) -> None:
        self.cooldown_bars = cooldown_bars_after_gap
        self.gap_bars_remaining = 0

    def check_gap(self, prev_close: float, curr_open: float, atr_val: float) -> bool:
        gap_dist = abs(curr_open - prev_close)
        if atr_val > 0 and gap_dist >= atr_val * 1.5:
            self.gap_bars_remaining = self.cooldown_bars
            return True
        if self.gap_bars_remaining > 0:
            self.gap_bars_remaining -= 1
            return True
        return False
