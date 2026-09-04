"""
AI AlgoTrading Agent Module (algotrading-lab/ai-algotrading-agent Adaptation)
=============================================================================

Target Integration: algotrading-lab/ai-algotrading-agent
Magic Number: 9100023

Provides multi-factor AI trading agent deliberation, technical indicator scoring,
0.05 INR price tick rounding, IST trading session validation, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100023


class AIAlgoTradingAgent:
    """
    AI AlgoTrading Agent for Indian equity markets (NSE/BSE).
    """

    def __init__(self, rsi_period: int = 14, macd_fast: int = 12, macd_slow: int = 26) -> None:
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.market_state = IndianMarketStateMachine()

    def calculate_rsi(self, closes: List[float]) -> float:
        if len(closes) < self.rsi_period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        avg_gain = sum(gains[-self.rsi_period :]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period :]) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def evaluate_agent_decision(
        self,
        symbol: str,
        closes: List[float],
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates multi-factor AI technical agent decision (RSI + MACD trend momentum).
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(current_price)

        if not session_valid or len(closes) < self.macd_slow:
            return {
                "symbol": symbol,
                "action": "HOLD",
                "price": rounded_price,
                "rsi": 50.0,
                "confidence": 0.0,
                "reason": "Market closed or insufficient history",
                "magic_number": MAGIC_NUMBER,
            }

        rsi = self.calculate_rsi(closes)
        fast_ema = float(sum(closes[-self.macd_fast :]) / self.macd_fast)
        slow_ema = float(sum(closes[-self.macd_slow :]) / self.macd_slow)
        macd_diff = fast_ema - slow_ema

        if rsi < 40.0 and macd_diff > 0:
            action = "BUY"
            confidence = min(1.0, 0.6 + (40.0 - rsi) / 100.0)
            reason = "RSI oversold recovery with bullish MACD momentum"
        elif rsi > 60.0 and macd_diff < 0:
            action = "SELL"
            confidence = min(1.0, 0.6 + (rsi - 60.0) / 100.0)
            reason = "RSI overbought rejection with bearish MACD momentum"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = "Neutral technical factor alignment"

        return {
            "symbol": symbol,
            "action": action,
            "price": rounded_price,
            "rsi": round(rsi, 2),
            "macd_diff": round(macd_diff, 2),
            "confidence": round(confidence, 2),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("algotrading_lab_agent", AIAlgoTradingAgent)
