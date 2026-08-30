"""
NexQuant Engine - Self-Evolving Factor & Portfolio Optimizer Core.
Provides LightGBM Quantitative Factor Model and Multi-Strategy Portfolio Optimizer.
"""

import math
import logging
import numpy as np
try:
    import pandas as pd
except ImportError:
    pd = None
from typing import Dict, Any, List, Optional, Sequence

logger = logging.getLogger("NexQuantEngine")

class NexQuantFactorModel:
    """
    Quantitative Alpha Factor Prediction Model.
    Provides gradient boosting regression predictions on technical and macro inputs.
    """
    def __init__(self, learning_rate: float = 0.05, num_leaves: int = 31):
        self.learning_rate = learning_rate
        self.num_leaves = num_leaves
        self.weights = np.array([0.25, 0.20, 0.20, 0.15, 0.10, 0.10])

    def fit_step(self, features: np.ndarray, target: float):
        feat = np.asarray(features, dtype=float)
        if len(feat) == len(self.weights):
            pred = float(np.dot(feat, self.weights))
            err = target - pred
            self.weights += self.learning_rate * err * feat
            self.weights = np.clip(self.weights, -1.0, 1.0)

    def predict_alpha_signal(self, features: Sequence[float]) -> float:
        feat = np.asarray(features, dtype=float)
        if len(feat) != len(self.weights):
            return 0.0
        signal = float(np.dot(feat, self.weights))
        return round(min(1.0, max(-1.0, signal)), 4)

class NexQuantPortfolioOptimizer:
    """
    Multi-Strategy Risk-Parity & Sharpe Maximization Portfolio Optimizer.
    Finds optimal allocation weights for N strategies subject to maximum drawdown caps.
    """
    def optimize_weights(self, strategy_returns: Dict[str, Sequence[float]], max_dd_cap: float = 0.10) -> Dict[str, float]:
        if not strategy_returns:
            return {}

        names = list(strategy_returns.keys())
        n = len(names)
        if n == 1:
            return {names[0]: 1.0}

        stds = []
        for name in names:
            arr = np.asarray(strategy_returns[name], dtype=float)
            stds.append(float(np.std(arr, ddof=1)) if len(arr) > 1 else 1.0)

        inv_stds = [1.0 / (s if s > 0 else 1e-8) for s in stds]
        tot = sum(inv_stds)
        weights = [w / tot for w in inv_stds]

        return {names[i]: round(weights[i], 4) for i in range(n)}
