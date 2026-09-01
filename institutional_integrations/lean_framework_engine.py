"""
Lean Algorithmic Trading Framework Engine (EQATS Institutional Adaptation)
Adapted from QuantConnect/Lean (Algorithm.Framework/Alphas & Risk modules)

Provides:
- PearsonCorrelationPairsTradingAlphaModel: Statistical Pairs Trading Pearson Correlation Solver & Ratio Signal Generator
- LeanMaximumDrawdownPercentPortfolio: Static & Trailing Drawdown Portfolio Risk Manager & Liquidation Target Generator
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

@dataclass
class PairCorrelationResult:
    asset1: str
    asset2: str
    correlation: float
    current_ratio: float
    mean_ratio: float
    std_ratio: float
    z_score: float
    signal: str

@dataclass
class LeanPortfolioTarget:
    symbol: str
    target_quantity: float
    reason: str

class PearsonCorrelationPairsTradingAlphaModel:
    """Lean Statistical Pairs Trading Pearson Correlation & Ratio Model."""

    def __init__(self, minimum_correlation: float=0.5, z_score_threshold: float=1.5) -> None:
        self.minimum_correlation = minimum_correlation
        self.z_score_threshold = z_score_threshold

    def find_best_pair(self, price_series_dict: Dict[str, List[float]]) -> Optional[PairCorrelationResult]:
        """Calculates Pearson correlation matrix across asset pairs and evaluates best ratio z-score signal."""
        symbols = sorted(list(price_series_dict.keys()))
        if len(symbols) < 2:
            return None
        best_corr = -1.0
        best_pair = None
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1, s2 = (symbols[i], symbols[j])
                p1, p2 = (price_series_dict[s1], price_series_dict[s2])
                min_len = min(len(p1), len(p2))
                if min_len < 5:
                    continue
                arr1 = np.array(p1[-min_len:])
                arr2 = np.array(p2[-min_len:])
                corr_matrix = np.corrcoef(arr1, arr2)
                corr = float(corr_matrix[0, 1]) if corr_matrix.shape == (2, 2) else 0.0
                if corr >= self.minimum_correlation and corr > best_corr:
                    best_corr = corr
                    ratios = arr1 / np.where(arr2 > 0, arr2, 1e-06)
                    mean_r = float(np.mean(ratios))
                    std_r = float(np.std(ratios, ddof=1)) if len(ratios) > 1 else 1e-06
                    curr_r = float(ratios[-1])
                    z_score = (curr_r - mean_r) / std_r if std_r > 0 else 0.0
                    signal = 'FLAT'
                    if z_score >= self.z_score_threshold:
                        signal = 'SHORT_PAIR'
                    elif z_score <= -self.z_score_threshold:
                        signal = 'LONG_PAIR'
                    best_pair = PairCorrelationResult(asset1=s1, asset2=s2, correlation=round(corr, 4), current_ratio=round(curr_r, 4), mean_ratio=round(mean_r, 4), std_ratio=round(std_r, 4), z_score=round(z_score, 2), signal=signal)
        return best_pair

class LeanMaximumDrawdownPercentPortfolio:
    """Lean Maximum Drawdown Portfolio Risk Manager."""

    def __init__(self, maximum_drawdown_percent: float=0.05, is_trailing: bool=True) -> None:
        self.maximum_drawdown_percent = -abs(maximum_drawdown_percent)
        self.is_trailing = is_trailing
        self.portfolio_high: float = 0.0
        self.initialized: bool = False

    def manage_risk(self, current_portfolio_value: float, active_symbols: List[str]) -> List[LeanPortfolioTarget]:
        """Evaluates static or trailing portfolio high-water mark and returns liquidation targets if breached."""
        if not self.initialized:
            self.portfolio_high = current_portfolio_value
            self.initialized = True
        if self.is_trailing and current_portfolio_value > self.portfolio_high:
            self.portfolio_high = current_portfolio_value
            return []
        dd_pct = current_portfolio_value / self.portfolio_high - 1.0 if self.portfolio_high > 0 else 0.0
        if dd_pct < self.maximum_drawdown_percent:
            self.initialized = False
            return [LeanPortfolioTarget(symbol=sym, target_quantity=0.0, reason=f'Lean Portfolio DD {dd_pct * 100.0:.2f}% breached limit {self.maximum_drawdown_percent * 100.0:.2f}% -> Liquidating') for sym in active_symbols]
        return []
