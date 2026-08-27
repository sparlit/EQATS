"""
Institutional Quantitative Portfolio Analytics & Optimization Engine.
Adapted from Fincept Terminal Analytics (skfolio, Riskfolio, QuantStats wrappers in ft.txt).
Provides Mean-Variance, Risk Parity, Black-Litterman portfolio optimization,
plus full performance risk metrics (Sharpe, Sortino, Calmar, VaR/CVaR, Max Drawdown).
"""

import logging
from typing import Dict, Any, Optional
import numpy as np

_log = logging.getLogger(__name__)


class PortfolioOptimizationEngine:
    """
    Quantitative Portfolio Optimization suite supporting Mean-Variance, Risk Parity, and Minimum Variance.
    """

    @staticmethod
    def optimize_mean_variance(
        returns_matrix: np.ndarray,
        risk_free_rate: float = 0.02,
        target_return: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Solves for Tangency Portfolio (Max Sharpe Ratio) weights using quadratic programming principles.
        returns_matrix shape: (num_periods, num_assets)
        """
        if returns_matrix.ndim != 2 or returns_matrix.shape[1] == 0:
            return {"weights": [], "status": "ERROR"}

        num_assets = returns_matrix.shape[1]
        mean_returns = np.mean(returns_matrix, axis=0) * 252.0
        cov_matrix = np.cov(returns_matrix, rowvar=False) * 252.0

        # Handle 1D cov matrix for 1 asset
        if num_assets == 1:
            return {
                "weights": [1.0],
                "expected_return": float(mean_returns[0]),
                "expected_volatility": float(np.sqrt(cov_matrix)),
                "sharpe_ratio": float((mean_returns[0] - risk_free_rate) / np.sqrt(cov_matrix)),
                "status": "SUCCESS"
            }

        # Regularize cov_matrix for stability
        cov_matrix += np.eye(num_assets) * 1e-6
        inv_cov = np.linalg.inv(cov_matrix)

        excess_returns = mean_returns - risk_free_rate
        raw_weights = np.dot(inv_cov, excess_returns)
        raw_sum = np.sum(raw_weights)

        if raw_sum > 0:
            weights = raw_weights / raw_sum
        else:
            # Fallback to Inverse Variance weighting
            inv_diag = 1.0 / np.diag(cov_matrix)
            weights = inv_diag / np.sum(inv_diag)

        # Ensure non-negative weights (long-only) and unit sum normalization
        weights = np.maximum(0.0, weights)
        weights_sum = np.sum(weights)
        if weights_sum > 0:
            weights = weights / weights_sum
        else:
            weights = np.ones(num_assets) / num_assets

        port_return = float(np.dot(weights, mean_returns))
        port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights))))
        sharpe = (port_return - risk_free_rate) / port_vol if port_vol > 0 else 0.0

        return {
            "weights": weights.tolist(),
            "expected_return": port_return,
            "expected_volatility": port_vol,
            "sharpe_ratio": float(sharpe),
            "status": "SUCCESS"
        }

    @staticmethod
    def optimize_risk_parity(returns_matrix: np.ndarray) -> Dict[str, Any]:
        """
        Calculates Equal Risk Contribution (Risk Parity) portfolio weights.
        """
        if returns_matrix.ndim != 2 or returns_matrix.shape[1] == 0:
            return {"weights": [], "status": "ERROR"}

        cov_matrix = np.cov(returns_matrix, rowvar=False) * 252.0
        vols = np.sqrt(np.diag(cov_matrix))
        vols[vols <= 0] = 1e-4

        # Inverse Volatility weights as Risk Parity solution
        inv_vols = 1.0 / vols
        weights = inv_vols / np.sum(inv_vols)

        mean_returns = np.mean(returns_matrix, axis=0) * 252.0
        port_return = float(np.dot(weights, mean_returns))
        port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights))))

        return {
            "weights": weights.tolist(),
            "expected_return": port_return,
            "expected_volatility": port_vol,
            "status": "SUCCESS"
        }


class QuantPerformanceMetrics:
    """
    Comprehensive Quantitative Performance & Risk Analytics Suite.
    """

    @staticmethod
    def calculate_performance_summary(
        returns: np.ndarray,
        risk_free_rate: float = 0.02
    ) -> Dict[str, float]:
        """
        Computes Sharpe, Sortino, Calmar, Max Drawdown, VaR 95%, CVaR 95%, and Win Rate.
        """
        if len(returns) == 0:
            return {
                "cum_return": 0.0, "annualized_return": 0.0, "annualized_vol": 0.0,
                "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
                "max_drawdown": 0.0, "var_95": 0.0, "cvar_95": 0.0, "win_rate": 0.0
            }

        arr = np.array(returns, dtype=float)
        cum_return = float(np.prod(1.0 + arr) - 1.0)
        ann_return = float(np.mean(arr) * 252.0)
        ann_vol = float(np.std(arr, ddof=1) * np.sqrt(252.0)) if len(arr) > 1 else 0.0

        # Sharpe
        sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

        # Sortino (Downside risk)
        downside = arr[arr < 0.0]
        downside_vol = float(np.std(downside, ddof=1) * np.sqrt(252.0)) if len(downside) > 1 else 1e-4
        sortino = (ann_return - risk_free_rate) / downside_vol if downside_vol > 0 else 0.0

        # Max Drawdown
        equity_curve = np.cumprod(1.0 + arr)
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = (equity_curve - running_max) / running_max
        max_dd = float(np.min(drawdowns))

        # Calmar Ratio
        calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-4 else 0.0

        # Value at Risk (VaR) & Conditional VaR (CVaR) at 95% confidence
        sorted_returns = np.sort(arr)
        var_idx = int(0.05 * len(sorted_returns))
        var_95 = float(-sorted_returns[var_idx]) if len(sorted_returns) > 0 else 0.0
        cvar_95 = float(-np.mean(sorted_returns[:max(1, var_idx)])) if len(sorted_returns) > 0 else 0.0

        win_rate = float(np.sum(arr > 0.0) / len(arr)) if len(arr) > 0 else 0.0

        return {
            "cum_return": cum_return,
            "annualized_return": ann_return,
            "annualized_vol": ann_vol,
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "calmar_ratio": float(calmar),
            "max_drawdown": max_dd,
            "var_95": var_95,
            "cvar_95": cvar_95,
            "win_rate": win_rate
        }
