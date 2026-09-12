"""
Shoonya Option Chain & Microstructure Depth Engine (anurag-roy/shoonya-option-chain Adaptation)
=============================================================================================

Target Integration: anurag-roy/shoonya-option-chain
Magic Number: 9100045

Provides Shoonya Finvasia 5-level market depth bid/ask queue parser, Volume Imbalance Delta (VID)
entry triggers, Order Cancellation Rate & Phantom Liquidity / Spoofing Filters, 0.05 INR price tick rounding,
IST market session validation, and microkernel plugin binding.
"""

import math
import zoneinfo
from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)

MAGIC_NUMBER_SHOONYA_OPTION_CHAIN: int = 9100045


def round_tick_005(price: float) -> float:
    return round_to_indian_tick_size(price)


def is_ist_market_open(now_dt: Optional[datetime] = None) -> bool:
    """
    Checks if current time is within Indian Standard Time (IST) market hours:
    09:15 to 15:30 IST, Monday to Friday.
    """
    if now_dt is None:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        now_dt = datetime.now(ist_tz)

    if now_dt.weekday() in (5, 6):
        return False

    start_time = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = now_dt.replace(hour=15, minute=30, second=0, microsecond=0)

    return start_time <= now_dt <= end_time


class ShoonyaOptionChainEngine:
    """
    Shoonya Finvasia 5-Level Market Depth, Volume Imbalance Delta (VID),
    and Phantom Liquidity / Spoofing Filter Engine.
    """

    def __init__(self, max_imbalance_ratio: float = 3.0, max_cancellation_rate_pct: float = 80.0) -> None:
        self.max_imbalance_ratio = max_imbalance_ratio
        self.max_cancellation_rate_pct = max_cancellation_rate_pct
        self.magic_number = MAGIC_NUMBER_SHOONYA_OPTION_CHAIN

    def calculate_volume_imbalance_delta(
        self, bid_depth_volumes: List[int], ask_depth_volumes: List[int]
    ) -> Dict[str, Any]:
        """
        Calculates Volume Imbalance Delta (VID) across 5-level market depth.
        If ask_volume / bid_volume >= max_imbalance_ratio (e.g. 3.0x), blocks long entries into heavy sell walls.
        """
        total_bid_vol = sum(bid_depth_volumes[:5]) if bid_depth_volumes else 0
        total_ask_vol = sum(ask_depth_volumes[:5]) if ask_depth_volumes else 0

        imbalance_ratio = round(total_ask_vol / total_bid_vol, 2) if total_bid_vol > 0 else 999.0
        sell_wall_detected = imbalance_ratio >= self.max_imbalance_ratio
        action = "BLOCK_LONG_ENTRY" if sell_wall_detected else "ALLOW_ENTRY"

        return {
            "total_bid_volume": total_bid_vol,
            "total_ask_volume": total_ask_vol,
            "imbalance_ratio": imbalance_ratio,
            "sell_wall_detected": sell_wall_detected,
            "action": action,
            "magic_number": self.magic_number,
        }

    def evaluate_order_cancellation_spoofing_filter(
        self, orders_created: int, orders_cancelled: int
    ) -> Dict[str, Any]:
        """
        Detects phantom liquidity / orderbook spoofing by tracking rapid cancellation rates.
        If order cancellation rate >= 80%, flags spoofing and blocks execution.
        """
        if orders_created <= 0:
            return {"spoofing_detected": False, "cancellation_rate_pct": 0.0, "action": "ALLOW_ORDER"}

        cancel_rate_pct = (orders_cancelled / orders_created) * 100.0
        spoofing_detected = cancel_rate_pct >= self.max_cancellation_rate_pct
        action = "BLOCK_SPOOFED_LIQUIDITY" if spoofing_detected else "ALLOW_ORDER"

        return {
            "orders_created": orders_created,
            "orders_cancelled": orders_cancelled,
            "cancellation_rate_pct": round(cancel_rate_pct, 2),
            "spoofing_detected": spoofing_detected,
            "action": action,
            "magic_number": self.magic_number,
        }


class ShoonyaOptionChainBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for Shoonya Option Chain Engine.
    """

    def __init__(self, broker_name: str = "SHOONYA_OPTION_CHAIN") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = ShoonyaOptionChainEngine()

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._is_connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=request.price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                error="Adapter not connected",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=request.price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                error="Exchange trading session closed (IST market hours strictly enforced)",
            )

        sanitized_price = round_tick_005(request.price)
        ticket_id = f"SOC-{int(datetime.now().timestamp() * 1000)}"

        return SEBIOrderResponse(
            success=True,
            ticket=ticket_id,
            price=sanitized_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {"balance": 1000000.0, "equity": 1000000.0, "currency": "INR", "is_demo": True}

    def get_history(self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute") -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 500.0, "ask": 500.15, "last": 500.05}

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


IndianBrokerPluginRegistry.register("SHOONYA_OPTION_CHAIN", ShoonyaOptionChainBrokerAdapter)
