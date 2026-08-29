"""
PySystemTrade Carver Systematic Trading Framework Engine (EQATS Institutional Adaptation)
Adapted from pst-group/pysystemtrade (sysquant/estimators & sysquant/optimisation)

Provides:
- DiversificationMultiplier: Calculates diversification multiplier for correlation-adjusted portfolio position sizing
- ShrinkagePortfolioOptimizer: Shrinks correlation matrices toward average correlation to stabilize portfolio weights
- ForecastScalar: Scales raw trading signals to a target average absolute forecast value of 10.0
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np


@dataclass
class CarverForecastScalarResult:
    scaled_forecasts: List[float]
    scaling_factor: float
    target_average: float


@dataclass
class CarverDiversificationResult:
    diversification_multiplier: float
    portfolio_variance: float
    weights: Dict[str, float]


class PySystemTradeEngine:
    """Rob Carver Systematic Trading Framework Engine."""

    def calculate_diversification_multiplier(
        self, weights: Dict[str, float], correlation_matrix: List[List[float]], max_multiplier: float = 2.5
    ) -> CarverDiversificationResult:
        """
        Calculates diversification multiplier = 1 / sqrt(w' * C * w).
        Increases position size allocation when trading uncorrelated or negatively correlated instruments.
        """
        symbols = sorted(list(weights.keys()))
        if not symbols or len(symbols) != len(correlation_matrix):
            return CarverDiversificationResult(1.0, 1.0, weights)

        w_vec = np.array([weights[sym] for sym in symbols])
        # Normalize weights
        if np.sum(np.abs(w_vec)) > 0:
            w_vec = w_vec / np.sum(np.abs(w_vec))

        c_mat = np.array(correlation_matrix)

        # Portfolio variance = w' * C * w
        port_var = float(np.dot(w_vec, np.dot(c_mat, w_vec)))
        port_std = math.sqrt(max(1e-6, port_var))

        raw_div_mult = 1.0 / port_std if port_std > 0 else 1.0
        div_mult = min(max_multiplier, max(1.0, raw_div_mult))

        return CarverDiversificationResult(
            diversification_multiplier=round(div_mult, 4),
            portfolio_variance=round(port_var, 6),
            weights={sym: round(float(w), 4) for sym, w in zip(symbols, w_vec)},
        )

    def shrink_correlation_matrix(
        self, correlation_matrix: List[List[float]], shrinkage_factor: float = 0.5
    ) -> List[List[float]]:
        """
        Shrinks off-diagonal elements of correlation matrix toward the average off-diagonal correlation.
        C_shrunk = (1 - delta) * C + delta * C_avg
        """
        c_mat = np.array(correlation_matrix)
        n = c_mat.shape[0]
        if n < 2:
            return correlation_matrix

        # Calculate average off-diagonal correlation
        mask = ~np.eye(n, dtype=bool)
        avg_corr = float(np.mean(c_mat[mask])) if np.any(mask) else 0.0

        shrunk_mat = c_mat.copy()
        for i in range(n):
            for j in range(n):
                if i != j:
                    shrunk_mat[i, j] = (1.0 - shrinkage_factor) * c_mat[i, j] + (shrinkage_factor * avg_corr)

        return shrunk_mat.tolist()

    def scale_forecast_signal(
        self, raw_signals: List[float], target_average_abs_forecast: float = 10.0
    ) -> CarverForecastScalarResult:
        """
        Scales raw strategy signals so their average absolute value equals target (default 10.0).
        Limits extreme outliers to [-20.0, +20.0].
        """
        if not raw_signals:
            return CarverForecastScalarResult([], 1.0, target_average_abs_forecast)

        raw_arr = np.array(raw_signals)
        mean_abs_raw = float(np.mean(np.abs(raw_arr)))

        scaling_factor = (target_average_abs_forecast / mean_abs_raw) if mean_abs_raw > 0 else 1.0
        scaled = raw_arr * scaling_factor

        # Cap forecasts to Carver bounds [-20.0, +20.0]
        scaled_capped = np.clip(scaled, -20.0, 20.0)

        return CarverForecastScalarResult(
            scaled_forecasts=[round(float(v), 2) for v in scaled_capped],
            scaling_factor=round(scaling_factor, 4),
            target_average=target_average_abs_forecast,
        )
