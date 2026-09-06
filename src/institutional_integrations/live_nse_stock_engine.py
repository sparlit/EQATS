"""
Live NSE Stock Engine (ashwanthkumar/Live-NSE-Stock Adaptation)
============================================================

Target Integration: ashwanthkumar/Live-NSE-Stock
Magic Number: 9100057

Provides live NSE quote JSON parsing, price percentage change calculation,
0.05 INR price tick rounding, IST market session validation, and microkernel plugin binding.
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

MAGIC_NUMBER_LIVE_NSE_STOCK: int = 9100057


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


class LiveNSEStockEngine:
    """
    Live Equity Quote Parser and Momentum Change Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_LIVE_NSE_STOCK

    def parse_quote_response(self, raw_quote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses live NSE equity quote payload into normalized market data.
        """
        if not raw_quote:
            return {"symbol": "", "last_price": 0.0, "p_change": 0.0, "volume": 0, "magic_number": self.magic_number}

        symbol = str(raw_quote.get("symbol", raw_quote.get("companyName", ""))).upper()
        last_price = float(raw_quote.get("lastPrice", raw_quote.get("last", 0.0)))
        prev_close = float(raw_quote.get("previousClose", raw_quote.get("prev_close", last_price)))
        volume = int(raw_quote.get("totalTradedVolume", raw_quote.get("volume", 0)))

        p_change = float(raw_quote.get("pChange", 0.0))
        if p_change == 0.0 and prev_close > 0.0:
            p_change = ((last_price - prev_close) / prev_close) * 100.0

        return {
            "symbol": symbol,
            "last_price": round_tick_005(last_price),
            "prev_close": round_tick_005(prev_close),
            "p_change": round(p_change, 2),
            "volume": volume,
            "magic_number": self.magic_number,
        }


class LiveNSEStockBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for Live NSE Stock Engine.
    """

    def __init__(self, broker_name: str = "LIVE_NSE_STOCK") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = LiveNSEStockEngine()

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
        ticket_id = f"LNS-{int(datetime.now().timestamp() * 1000)}"

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


# Register in microkernel plugin registry
IndianBrokerPluginRegistry.register("LIVE_NSE_STOCK", LiveNSEStockBrokerAdapter)
