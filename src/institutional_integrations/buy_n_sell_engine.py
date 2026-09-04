"""
BuyNSell Engine Module (akt114/BuyNSell Adaptation)
==================================================

Target Integration: akt114/BuyNSell
Magic Number: 9100020

Provides automated quantitative buy/sell momentum signal generation, EMA trend filtering,
volume confirmation, 0.05 INR price tick rounding, and dynamic microkernel registration.
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

MAGIC_NUMBER: int = 9100020


class BuyNSellEngine:
    """
    Quantitative Buy/Sell momentum signal engine for Indian equity markets (NSE/BSE).
    """

    def __init__(self, fast_period: int = 9, slow_period: int = 21, volume_factor: float = 1.2) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.volume_factor = volume_factor
        self.market_state = IndianMarketStateMachine()

    def calculate_ema(self, prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return float(sum(prices) / len(prices))
        multiplier = 2.0 / (period + 1)
        ema = float(sum(prices[:period]) / period)
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def evaluate_signal(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[float],
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates buy/sell momentum signals based on EMA crossover and volume confirmation.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(current_price)

        if not session_valid or len(prices) < self.slow_period:
            return {
                "symbol": symbol,
                "action": "HOLD",
                "price": rounded_price,
                "confidence": 0.0,
                "reason": "Market session closed" if not session_valid else "Insufficient price history",
                "magic_number": MAGIC_NUMBER,
            }

        fast_ema = self.calculate_ema(prices, self.fast_period)
        slow_ema = self.calculate_ema(prices, self.slow_period)

        avg_volume = float(sum(volumes[-10:]) / len(volumes[-10:])) if len(volumes) >= 10 else 1.0
        current_volume = volumes[-1] if volumes else 0.0
        volume_confirmed = current_volume >= (avg_volume * self.volume_factor)

        if fast_ema > slow_ema and volume_confirmed:
            action = "BUY"
            confidence = min(1.0, 0.6 + 0.4 * (current_volume / (avg_volume + 1e-6)))
            reason = "Bullish EMA crossover with volume surge"
        elif fast_ema < slow_ema and volume_confirmed:
            action = "SELL"
            confidence = min(1.0, 0.6 + 0.4 * (current_volume / (avg_volume + 1e-6)))
            reason = "Bearish EMA crossover with volume confirmation"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = "Neutral momentum / unconfirmed volume"

        return {
            "symbol": symbol,
            "action": action,
            "price": rounded_price,
            "fast_ema": round(fast_ema, 2),
            "slow_ema": round(slow_ema, 2),
            "volume_surge": volume_confirmed,
            "confidence": round(confidence, 2),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("akt114_buynsell", BuyNSellEngine)
