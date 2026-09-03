"""
mt5Bot Integration Engine.
Provides Volume Quantization & Normalization, Order Age Expiration Filter,
and Relative Price Prediction Gap Evaluator.
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MT5BotEngine")


class MT5BotVolumeNormalizer:
    """
    Broker-Compliant Volume Normalization & Step Quantization.
    """

    def normalize_volume(
        self, desired_volume: float, min_volume: float = 0.01, max_volume: float = 100.0, step_volume: float = 0.01,
    ) -> float:
        v = float(desired_volume)
        min_v = float(min_volume)
        max_v = float(max_volume)
        step_v = float(step_volume) if step_volume > 0 else 0.01
        if v < min_v:
            return min_v
        if v > max_v:
            return max_v
        steps = round((v - min_v) / step_v)
        normalized = steps * step_v + min_v
        return round(max(min_v, min(max_v, normalized)), 2)


class RelativePricePredictionEvaluator:
    """
    Evaluates relative price gap percentage between ML predicted price and current price.
    """

    def evaluate_prediction_gap(
        self, current_price: float, predicted_price: float, min_gap_pct: float = 1.0,
    ) -> dict[str, Any]:
        if current_price <= 0:
            return {"action": "HOLD", "gap_pct": 0.0}
        gap_pct = (predicted_price - current_price) / current_price * 100.0
        if gap_pct >= min_gap_pct:
            return {"action": "BUY", "gap_pct": round(gap_pct, 2)}
        if gap_pct <= -min_gap_pct:
            return {"action": "SELL", "gap_pct": round(gap_pct, 2)}
        return {"action": "HOLD", "gap_pct": round(gap_pct, 2)}
