"""
Metatrader Meta Edge & Quantitative Execution Analytics.
Provides Probabilistic Sharpe Ratio (PSR), Calmar Ratio, Sortino Ratio, Kelly Sizing Fraction,
Institutional Edge Score, and Real-Time Execution Slippage Tracker.
"""

import time
import math
import numpy as np
import threading
import logging
from typing import Dict, Any, List, Optional, Sequence

logger = logging.getLogger("MetaEdgeQuant")

def calculate_probabilistic_sharpe_ratio(
    returns: Sequence[float],
    benchmark_sharpe: float = 0.0
) -> float:
    """
    Calculates Probabilistic Sharpe Ratio (PSR) from Bailey & López de Prado (2012).
    Evaluates probability that true Sharpe ratio is greater than benchmark_sharpe given
    sample size, skewness, and kurtosis.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 5:
        return 0.5

    mean_r = float(np.mean(r))
    std_r = float(np.std(r, ddof=1))
    if std_r <= 1e-8:
        return 0.5

    sr = mean_r / std_r
    skew = float(np.mean(((r - mean_r) / std_r) ** 3))
    kurt = float(np.mean(((r - mean_r) / std_r) ** 4))

    # Variance of Sharpe Ratio estimate
    sr_var = (1.0 + 0.5 * (sr ** 2) - skew * sr + ((kurt - 3.0) / 4.0) * (sr ** 2)) / (n - 1)
    if sr_var <= 0:
        return 0.5

    sr_std = math.sqrt(sr_var)
    z_stat = (sr - benchmark_sharpe) / sr_std

    # CDF of standard normal
    psr = 0.5 * (1.0 + math.erf(z_stat / math.sqrt(2.0)))
    return round(min(0.999, max(0.001, psr)), 4)

def calculate_kelly_fraction(win_rate: float, reward_risk_ratio: float) -> float:
    """
    Calculates Kelly Criterion optimal compounding fraction.
    Kelly = (WinRate * R - (1 - WinRate)) / R
    """
    if reward_risk_ratio <= 0:
        return 0.0
    k = (win_rate * reward_risk_ratio - (1.0 - win_rate)) / reward_risk_ratio
    return round(max(0.0, min(0.25, k)), 4)

def calculate_calmar_ratio(annualized_return: float, max_drawdown_pct: float) -> float:
    """Calculates Calmar Ratio = Annualized Return / Max Drawdown."""
    dd = abs(max_drawdown_pct)
    if dd <= 1e-8:
        return 0.0
    return round(annualized_return / dd, 2)

def calculate_edge_score(
    expectancy_per_trade: float,
    win_rate: float,
    reward_risk_ratio: float,
    returns: Sequence[float],
    annualized_return: float = 20.0,
    max_drawdown_pct: float = 10.0
) -> Dict[str, Any]:
    """
    Computes institutional 0..100 composite Edge Score combining Expectancy, Kelly fraction,
    Probabilistic Sharpe Ratio (PSR), and Calmar ratio.
    """
    kelly = calculate_kelly_fraction(win_rate, reward_risk_ratio)
    psr = calculate_probabilistic_sharpe_ratio(returns, benchmark_sharpe=0.0)
    calmar = calculate_calmar_ratio(annualized_return, max_drawdown_pct)

    exp_score = min(100.0, max(0.0, expectancy_per_trade * 10.0))
    kelly_score = kelly * 400.0
    psr_score = psr * 100.0
    calmar_score = min(100.0, calmar * 25.0)

    composite_score = (0.25 * exp_score) + (0.25 * kelly_score) + (0.25 * psr_score) + (0.25 * calmar_score)
    return {
        "edge_score": round(composite_score, 1),
        "kelly_fraction": kelly,
        "probabilistic_sharpe_ratio": psr,
        "calmar_ratio": calmar,
        "is_deploy_safe": psr >= 0.70 and kelly > 0.0 and composite_score >= 50.0
    }

class EmpiricalSlippageTracker:
    """
    Tracks empirical signal-vs-fill execution price slippage.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.events = []

    def record_fill(self, symbol: str, signal_price: float, fill_price: float, atr: float = 0.0010):
        with self._lock:
            slippage = abs(fill_price - signal_price)
            atr_frac = (slippage / atr) if atr > 0 else 0.0
            self.events.append({
                "symbol": symbol,
                "signal_price": signal_price,
                "fill_price": fill_price,
                "slippage": round(slippage, 5),
                "slippage_atr_frac": round(atr_frac, 4),
                "timestamp": time.time()
            })

    def get_symbol_stats(self, symbol: str) -> Dict[str, float]:
        with self._lock:
            sym_events = [e for e in self.events if e["symbol"] == symbol]
            if not sym_events:
                return {"mean_slippage": 0.0, "mean_atr_frac": 0.0, "count": 0}
            mean_slip = sum(e["slippage"] for e in sym_events) / len(sym_events)
            mean_frac = sum(e["slippage_atr_frac"] for e in sym_events) / len(sym_events)
            return {
                "mean_slippage": round(mean_slip, 5),
                "mean_atr_frac": round(mean_frac, 4),
                "count": len(sym_events)
            }
