"""
Kite Option Chain Engine (anurag-roy/kite-option-chain Adaptation)
=================================================================

Target Integration: anurag-roy/kite-option-chain
Magic Number: 9100027

Provides Zerodha Kite option chain strike matrix parsing, Put-Call Ratio (PCR) analytics,
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

MAGIC_NUMBER: int = 9100027


class KiteOptionChainEngine:
    """
    Zerodha Kite Option Chain & PCR Analysis Engine for NIFTY / BANKNIFTY derivatives.
    """

    def __init__(self, pcr_bullish_threshold: float = 1.1, pcr_bearish_threshold: float = 0.8) -> None:
        self.pcr_bullish_threshold = pcr_bullish_threshold
        self.pcr_bearish_threshold = pcr_bearish_threshold
        self.market_state = IndianMarketStateMachine()

    def calculate_pcr(self, call_oi: List[int], put_oi: List[int]) -> float:
        total_call_oi = sum(call_oi)
        total_put_oi = sum(put_oi)
        if total_call_oi == 0:
            return 1.0
        return float(total_put_oi / total_call_oi)

    def analyze_option_chain(
        self,
        symbol: str,
        underlying_price: float,
        strikes: List[float],
        call_oi: List[int],
        put_oi: List[int],
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Parses option chain strikes and evaluates market sentiment via Put-Call Ratio (PCR).
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_underlying = round_to_indian_tick_size(underlying_price)

        if not session_valid or not call_oi or not put_oi or len(call_oi) != len(put_oi):
            return {
                "symbol": symbol,
                "underlying_price": rounded_underlying,
                "pcr": 1.0,
                "sentiment": "NEUTRAL",
                "max_pain_strike": rounded_underlying,
                "reason": "Market session closed or invalid chain data",
                "magic_number": MAGIC_NUMBER,
            }

        pcr = self.calculate_pcr(call_oi, put_oi)

        if pcr >= self.pcr_bullish_threshold:
            sentiment = "BULLISH"
            reason = f"High Put-Call Ratio ({pcr:.2f} >= {self.pcr_bullish_threshold}) indicates strong put writing support"
        elif pcr <= self.pcr_bearish_threshold:
            sentiment = "BEARISH"
            reason = f"Low Put-Call Ratio ({pcr:.2f} <= {self.pcr_bearish_threshold}) indicates heavy call resistance"
        else:
            sentiment = "NEUTRAL"
            reason = f"Balanced Put-Call Ratio ({pcr:.2f})"

        # Calculate Max Pain Strike
        min_loss = float("inf")
        max_pain_strike = rounded_underlying
        for k in range(len(strikes)):
            strike_price = strikes[k]
            total_loss = 0.0
            for j in range(len(strikes)):
                s = strikes[j]
                if s < strike_price:
                    total_loss += (strike_price - s) * call_oi[j]
                elif s > strike_price:
                    total_loss += (s - strike_price) * put_oi[j]
            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = strike_price

        return {
            "symbol": symbol,
            "underlying_price": rounded_underlying,
            "pcr": round(pcr, 4),
            "sentiment": sentiment,
            "max_pain_strike": round_to_indian_tick_size(max_pain_strike),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("anurag_roy_kite_optionchain", KiteOptionChainEngine)
