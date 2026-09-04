"""
OsEngine Multi-Symbol Strategy Engine (AlexWan/OsEngine Adaptation)
===================================================================

Target Integration: AlexWan/OsEngine
Magic Number: 9100022

Provides Donchian channel breakout strategy logic, trailing drawdown stop-loss,
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

MAGIC_NUMBER: int = 9100022


class OsEngineTrader:
    """
    OsEngine Multi-Symbol Breakout & Trailing Drawdown Strategy Engine.
    """

    def __init__(self, channel_period: int = 20, max_drawdown_pct: float = 2.0) -> None:
        self.channel_period = channel_period
        self.max_drawdown_pct = max_drawdown_pct
        self.market_state = IndianMarketStateMachine()

    def evaluate_breakout(
        self,
        symbol: str,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        current_price: float,
        entry_price: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates Donchian channel upper/lower breakouts and enforces trailing drawdown exits.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(current_price)

        if not session_valid or len(closes) < self.channel_period:
            return {
                "symbol": symbol,
                "action": "HOLD",
                "price": rounded_price,
                "confidence": 0.0,
                "reason": "Market closed or insufficient history",
                "magic_number": MAGIC_NUMBER,
            }

        upper_channel = float(max(highs[-self.channel_period :]))
        lower_channel = float(min(lows[-self.channel_period :]))

        # Check trailing drawdown boundary if in active position
        if entry_price > 0:
            drawdown_pct = float((entry_price - rounded_price) / entry_price) * 100.0
            if drawdown_pct >= self.max_drawdown_pct:
                return {
                    "symbol": symbol,
                    "action": "SELL",
                    "price": rounded_price,
                    "drawdown_pct": round(drawdown_pct, 2),
                    "confidence": 1.0,
                    "reason": f"Trailing drawdown boundary breach ({drawdown_pct:.2f}% >= {self.max_drawdown_pct}%)",
                    "magic_number": MAGIC_NUMBER,
                }

        if rounded_price >= upper_channel:
            action = "BUY"
            confidence = 0.85
            reason = "Donchian upper channel breakout"
        elif rounded_price <= lower_channel:
            action = "SELL"
            confidence = 0.85
            reason = "Donchian lower channel breakdown"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = "Price within Donchian channel boundaries"

        return {
            "symbol": symbol,
            "action": action,
            "price": rounded_price,
            "upper_channel": round(upper_channel, 2),
            "lower_channel": round(lower_channel, 2),
            "confidence": round(confidence, 2),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("alexwan_osengine", OsEngineTrader)
