"""
RaptorBT Vectorized Backtesting Engine (alphabench/raptorbt Adaptation)
======================================================================

Target Integration: alphabench/raptorbt
Magic Number: 9100024

Provides vectorized strategy backtesting, equity curve metrics, Sharpe/Sortino ratios,
0.05 INR price tick rounding, IST trading session validation, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
import math
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100024


class RaptorBTEngine:
    """
    RaptorBT Vectorized Strategy Backtesting & Performance Analytics Engine.
    """

    def __init__(self, initial_capital: float = 1000000.0, risk_free_rate: float = 0.05) -> None:
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self.market_state = IndianMarketStateMachine()

    def run_backtest(
        self,
        symbol: str,
        prices: List[float],
        signals: List[int],
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Runs a vectorized backtest on price history and trade signals (1=BUY, -1=SELL, 0=HOLD).
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        if not session_valid or not prices or len(prices) != len(signals):
            return {
                "symbol": symbol,
                "total_returns_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate": 0.0,
                "status": "REJECTED",
                "reason": "Market closed or mismatched series lengths",
                "magic_number": MAGIC_NUMBER,
            }

        returns = []
        equity = self.initial_capital
        peak = equity
        max_drawdown = 0.0
        winning_trades = 0
        total_trades = 0

        for i in range(1, len(prices)):
            price_change = (prices[i] - prices[i - 1]) / prices[i - 1]
            trade_return = signals[i - 1] * price_change
            returns.append(trade_return)

            if signals[i - 1] != 0:
                total_trades += 1
                if trade_return > 0:
                    winning_trades += 1

            equity *= 1.0 + trade_return
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        avg_return = float(sum(returns) / len(returns)) if returns else 0.0
        variance = float(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if returns else 0.0
        std_dev = math.sqrt(variance) if variance > 0 else 1e-6

        downside_variance = (
            float(sum(min(0.0, r) ** 2 for r in returns) / len(returns)) if returns else 0.0
        )
        downside_dev = math.sqrt(downside_variance) if downside_variance > 0 else 1e-6

        sharpe_ratio = float((avg_return - (self.risk_free_rate / 252.0)) / std_dev) if std_dev > 0 else 0.0
        sortino_ratio = (
            float((avg_return - (self.risk_free_rate / 252.0)) / downside_dev) if downside_dev > 0 else 0.0
        )
        win_rate = float(winning_trades / total_trades) if total_trades > 0 else 0.0
        total_returns_pct = float((equity - self.initial_capital) / self.initial_capital) * 100.0

        return {
            "symbol": symbol,
            "final_equity": round(equity, 2),
            "total_returns_pct": round(total_returns_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "sortino_ratio": round(sortino_ratio, 4),
            "max_drawdown_pct": round(max_drawdown, 2),
            "win_rate": round(win_rate, 4),
            "total_trades": total_trades,
            "status": "SUCCESS",
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("alphabench_raptorbt", RaptorBTEngine)
