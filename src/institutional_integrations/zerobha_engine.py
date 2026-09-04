"""
Zerobha Zerodha Trading Automation Engine (althk/zerobha Adaptation)
====================================================================

Target Integration: althk/zerobha
Magic Number: 9100025

Provides automated Zerodha Kite order execution framing, Bracket Order (BO) target/stop-loss
risk governance, 0.05 INR price tick rounding, IST trading session validation, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100025


class ZerobhaEngine:
    """
    Zerobha Order Framing & Risk Governance Engine for Zerodha Kite.
    """

    def __init__(self, default_target_pct: float = 1.0, default_sl_pct: float = 0.5) -> None:
        self.default_target_pct = default_target_pct
        self.default_sl_pct = default_sl_pct
        self.market_state = IndianMarketStateMachine()

    def frame_bracket_order(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        target_pct: Optional[float] = None,
        sl_pct: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Frames Zerodha Bracket Order (BO) / Cover Order (CO) parameters with 0.05 INR tick rounding.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(price)
        rounded_qty = round_to_indian_quantity(quantity)

        if not session_valid:
            return {
                "symbol": symbol,
                "side": side.upper(),
                "price": rounded_price,
                "quantity": rounded_qty,
                "target_price": 0.0,
                "sl_price": 0.0,
                "status": "REJECTED",
                "reason": "Market closed",
                "magic_number": MAGIC_NUMBER,
            }

        target_multiplier = (target_pct or self.default_target_pct) / 100.0
        sl_multiplier = (sl_pct or self.default_sl_pct) / 100.0

        if side.upper() == "BUY":
            target_price = round_to_indian_tick_size(rounded_price * (1.0 + target_multiplier))
            sl_price = round_to_indian_tick_size(rounded_price * (1.0 - sl_multiplier))
        else:
            target_price = round_to_indian_tick_size(rounded_price * (1.0 - target_multiplier))
            sl_price = round_to_indian_tick_size(rounded_price * (1.0 + sl_multiplier))

        return {
            "symbol": symbol,
            "side": side.upper(),
            "price": rounded_price,
            "quantity": rounded_qty,
            "target_price": target_price,
            "sl_price": sl_price,
            "product": "MIS",
            "exchange": "NSE",
            "status": "READY",
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("althk_zerobha", ZerobhaEngine)
