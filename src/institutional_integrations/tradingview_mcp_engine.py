"""
TradingView MCP Engine (atilaahmettaner/tradingview-mcp Adaptation)
====================================================================

Target Integration: atilaahmettaner/tradingview-mcp
Magic Number: 9100059

Provides Model Context Protocol (MCP) tool bindings for TradingView technical indicators,
recommendation summary aggregation (BUY/SELL/NEUTRAL), 0.05 INR price tick rounding,
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

MAGIC_NUMBER_TRADINGVIEW_MCP: int = 9100059


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


class TradingViewMCPEngine:
    """
    Model Context Protocol (MCP) Indicator & Technical Analysis Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_TRADINGVIEW_MCP

    def compute_technical_summary(self, prices: List[float]) -> Dict[str, Any]:
        """
        Computes TradingView-style technical recommendation summary across moving averages and RSI.
        """
        if not prices or len(prices) < 20:
            return {"recommendation": "NEUTRAL", "buy_signals": 0, "sell_returns": 0, "magic_number": self.magic_number}

        latest_price = prices[-1]
        sma_20 = sum(prices[-20:]) / 20.0
        sma_10 = sum(prices[-10:]) / 10.0 if len(prices) >= 10 else sma_20

        # Simple RSI calculation
        gains = [max(0.0, prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        losses = [max(0.0, prices[i - 1] - prices[i]) for i in range(1, len(prices))]
        avg_gain = sum(gains[-14:]) / 14.0 if len(gains) >= 14 else 0.01
        avg_loss = sum(losses[-14:]) / 14.0 if len(losses) >= 14 else 0.01
        rs = avg_gain / avg_loss if avg_loss > 0 else 1.0
        rsi = 100.0 - (100.0 / (1.0 + rs))

        buy_count = 0
        sell_count = 0

        if latest_price > sma_20:
            buy_count += 1
        else:
            sell_count += 1

        if latest_price > sma_10:
            buy_count += 1
        else:
            sell_count += 1

        if rsi < 30.0:
            buy_count += 2
        elif rsi > 70.0:
            sell_count += 2

        if buy_count > sell_count:
            recommendation = "STRONG_BUY" if buy_count >= 3 else "BUY"
        elif sell_count > buy_count:
            recommendation = "STRONG_SELL" if sell_count >= 3 else "SELL"
        else:
            recommendation = "NEUTRAL"

        return {
            "symbol_price": round_tick_005(latest_price),
            "recommendation": recommendation,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "rsi": round(rsi, 2),
            "sma_20": round_tick_005(sma_20),
            "magic_number": self.magic_number,
        }


class TradingViewMCPBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for TradingView MCP Engine.
    """

    def __init__(self, broker_name: str = "TRADINGVIEW_MCP") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = TradingViewMCPEngine()

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
        ticket_id = f"TVMCP-{int(datetime.now().timestamp() * 1000)}"

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
IndianBrokerPluginRegistry.register("TRADINGVIEW_MCP", TradingViewMCPBrokerAdapter)
