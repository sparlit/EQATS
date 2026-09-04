"""
NSE Order Flow & Volume Delta Engine (alloc7260/NSE Adaptation)
==============================================================

Target Integration: alloc7260/NSE
Magic Number: 9100021

Provides high-frequency Order Flow Imbalance (OFI), Cumulative Volume Delta (CVD),
0.05 INR price tick rounding, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100021


class NSEOrderFlowEngine:
    """
    NSE Order Flow & Volume Delta Engine for Indian equity derivatives (NSE/NFO).
    """

    def __init__(self, delta_threshold: float = 1.5) -> None:
        self.delta_threshold = delta_threshold
        self.market_state = IndianMarketStateMachine()

    def calculate_order_flow_imbalance(self, bid_volumes: List[float], ask_volumes: List[float]) -> float:
        """
        Calculates Order Flow Imbalance (OFI) ratio between total bid volume and total ask volume.
        """
        total_bid = float(sum(bid_volumes))
        total_ask = float(sum(ask_volumes))
        if total_bid + total_ask == 0:
            return 0.0
        return float((total_bid - total_ask) / (total_bid + total_ask))

    def evaluate_order_flow(
        self,
        symbol: str,
        bid_volumes: List[float],
        ask_volumes: List[float],
        last_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates real-time NSE order flow imbalance and volume delta signals.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(last_price)

        if not session_valid or not bid_volumes or not ask_volumes:
            return {
                "symbol": symbol,
                "action": "HOLD",
                "price": rounded_price,
                "ofi": 0.0,
                "cvd": 0.0,
                "confidence": 0.0,
                "reason": "Market closed or empty depth",
                "magic_number": MAGIC_NUMBER,
            }

        ofi = self.calculate_order_flow_imbalance(bid_volumes, ask_volumes)
        cvd = float(sum(bid_volumes) - sum(ask_volumes))

        if ofi >= 0.35 and cvd > 0:
            action = "BUY"
            confidence = min(1.0, 0.5 + abs(ofi))
            reason = "Institutional buy order flow imbalance"
        elif ofi <= -0.35 and cvd < 0:
            action = "SELL"
            confidence = min(1.0, 0.5 + abs(ofi))
            reason = "Institutional sell order flow imbalance"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = "Balanced order book pressure"

        return {
            "symbol": symbol,
            "action": action,
            "price": rounded_price,
            "ofi": round(ofi, 4),
            "cvd": round(cvd, 2),
            "confidence": round(confidence, 2),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("alloc7260_nse_orderflow", NSEOrderFlowEngine)
