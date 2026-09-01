"""
Backtrader Analyzers & Position Sizers Suite (EQATS Institutional Adaptation)
Adapted from mementum/backtrader (analyzers & sizers modules)

Provides:
- BacktraderAnalyzerEngine:
  - System Quality Number (SQN = sqrt(N) * avg_trade / std_trade)
  - Variability-Weighted Return (VWR = return * (1 - (std_returns / mean_returns)))
  - Calmar Ratio (annualized return / max drawdown)
  - Annual Return & DrawDown Metrics
- BacktraderSizerEngine:
  - PercentSizer (% account equity position sizing)
  - RiskSizer (Fixed monetary risk per trade based on SL distance in pips)
  - FixedSizer (Fixed lot sizing with account balance floor check)
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

@dataclass
class BacktraderPerformanceMetrics:
    total_trades: int
    sqn_score: float
    vwr_score: float
    calmar_ratio: float
    annual_return_pct: float
    max_drawdown_pct: float
    win_rate: float

@dataclass
class BacktraderSizerResult:
    lot_size: float
    risk_amount_usd: float
    risk_pct: float
    sizer_type: str

class BacktraderAnalyzerEngine:
    """Backtrader Performance & System Quality Analyzer."""

    def evaluate_performance(self, returns: List[float], trade_pnls: List[float], initial_balance: float=100000.0, years: float=1.0) -> BacktraderPerformanceMetrics:
        """Calculates SQN, VWR, Calmar Ratio, and DrawDown metrics."""
        if not trade_pnls or len(trade_pnls) < 2:
            return BacktraderPerformanceMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        pnl_arr = np.array(trade_pnls)
        n = len(pnl_arr)
        avg_pnl = float(np.mean(pnl_arr))
        std_pnl = float(np.std(pnl_arr, ddof=1)) if n > 1 else 1e-06
        sqn = math.sqrt(n) * avg_pnl / std_pnl if std_pnl > 0 else 0.0
        ret_arr = np.array(returns) if returns else pnl_arr / initial_balance
        mean_ret = float(np.mean(ret_arr))
        std_ret = float(np.std(ret_arr, ddof=1)) if len(ret_arr) > 1 else 1e-06
        vwr = mean_ret * (1.0 - std_ret / (abs(mean_ret) + 1e-06)) if abs(mean_ret) > 0 else 0.0
        cum_pnl = np.cumsum(pnl_arr)
        equity_curve = initial_balance + cum_pnl
        peak = np.maximum.accumulate(equity_curve)
        dd = (peak - equity_curve) / peak * 100.0
        max_dd_pct = float(np.max(dd)) if len(dd) > 0 else 0.0
        tot_pnl = float(np.sum(pnl_arr))
        tot_ret_pct = tot_pnl / initial_balance * 100.0
        ann_ret_pct = tot_ret_pct / max(0.1, years)
        calmar = ann_ret_pct / max_dd_pct if max_dd_pct > 0 else 0.0
        wins = np.sum(pnl_arr > 0)
        win_rate = wins / float(n) * 100.0
        return BacktraderPerformanceMetrics(total_trades=n, sqn_score=round(sqn, 2), vwr_score=round(vwr, 4), calmar_ratio=round(calmar, 2), annual_return_pct=round(ann_ret_pct, 2), max_drawdown_pct=round(max_dd_pct, 2), win_rate=round(win_rate, 1))

class BacktraderSizerEngine:
    """Backtrader Position Sizer Engine."""

    def percent_sizer(self, account_equity: float, percent: float=2.0, leverage: float=100.0) -> BacktraderSizerResult:
        """Sizes position as % of account equity."""
        risk_usd = account_equity * (percent / 100.0)
        notional = risk_usd * leverage
        lot_size = round(notional / 100000.0, 2)
        return BacktraderSizerResult(lot_size=max(0.01, lot_size), risk_amount_usd=risk_usd, risk_pct=percent, sizer_type='PercentSizer')

    def risk_sizer(self, account_equity: float, risk_pct: float=1.0, stop_loss_pips: float=20.0, pip_value_per_lot: float=10.0) -> BacktraderSizerResult:
        """Sizes position based on fixed monetary risk per trade and SL distance."""
        if stop_loss_pips <= 0 or pip_value_per_lot <= 0:
            return BacktraderSizerResult(0.01, 0.0, 0.0, 'RiskSizer')
        risk_usd = account_equity * (risk_pct / 100.0)
        risk_per_lot = stop_loss_pips * pip_value_per_lot
        raw_lots = risk_usd / risk_per_lot if risk_per_lot > 0 else 0.0
        return BacktraderSizerResult(lot_size=max(0.01, round(raw_lots, 2)), risk_amount_usd=risk_usd, risk_pct=risk_pct, sizer_type='RiskSizer')
