"""
Calculus Quant Engine.
Provides Hull Moving Average (HMA) calculation engine, Information Entropy / Market Jitter Monitor,
and Geometric Exit Target Calculator.
"""
import math
import logging
import numpy as np
from typing import Dict, Any, List, Optional, Sequence
logger = logging.getLogger('CalculusQuantEngine')

def calculate_wma(data: Sequence[float], period: int) -> float:
    """Calculates Weighted Moving Average (WMA)."""
    p = np.asarray(data[-period:], dtype=float)
    if len(p) < period or period <= 0:
        return 0.0
    weights = np.arange(1, period + 1, dtype=float)
    return float(np.sum(p * weights) / np.sum(weights))

def calculate_hma(prices: Sequence[float], period: int=14) -> float:
    """
    Calculates Hull Moving Average (HMA).
    HMA = WMA(2 * WMA(n/2) - WMA(n), sqrt(n))
    """
    p = np.asarray(prices, dtype=float)
    half_period = max(1, period // 2)
    sqrt_period = max(1, int(math.sqrt(period)))
    if len(p) < period + sqrt_period:
        return float(p[-1]) if len(p) > 0 else 0.0
    diff_series = []
    for i in range(len(p) - sqrt_period, len(p)):
        sub = p[:i + 1]
        wma_half = calculate_wma(sub, half_period)
        wma_full = calculate_wma(sub, period)
        diff_series.append(2.0 * wma_half - wma_full)
    return calculate_wma(diff_series, sqrt_period)

class MarketEntropyMonitor:
    """
    Market Information Entropy & Jitter Monitor.
    Evaluates price noise level and entropy to filter chaotic price movements.
    """

    def compute_noise_level(self, prices: Sequence[float]) -> float:
        p = np.asarray(prices, dtype=float)
        if len(p) < 2:
            return 0.0
        abs_diff = float(np.abs(p[-1] - p[0]))
        total_path = float(np.sum(np.abs(np.diff(p))))
        efficiency_ratio = abs_diff / total_path if total_path > 0 else 1.0
        noise_level = 1.0 - efficiency_ratio
        return round(noise_level, 4)

class GeometricExitEngine:
    """
    Geometric Exit & Dynamic Ratio Scaling Engine.
    """

    def compute_geometric_exit(self, entry_price: float, sl_price: float, geometric_ratio: float=1.618) -> Dict[str, float]:
        risk_dist = abs(entry_price - sl_price)
        tp1 = entry_price + risk_dist * geometric_ratio if entry_price >= sl_price else entry_price - risk_dist * geometric_ratio
        tp2 = entry_price + risk_dist * geometric_ratio ** 2 if entry_price >= sl_price else entry_price - risk_dist * geometric_ratio ** 2
        return {'entry_price': round(entry_price, 5), 'sl_price': round(sl_price, 5), 'tp1_geometric': round(tp1, 5), 'tp2_geometric': round(tp2, 5), 'risk_dist': round(risk_dist, 5)}
