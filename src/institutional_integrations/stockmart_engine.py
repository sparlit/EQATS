"""
StockMart Simulation Engine (ayushmaanbhav/stockmart Adaptation)
============================================================

Target Integration: ayushmaanbhav/stockmart
Magic Number: 9100066

Provides orderbook limit matching, portfolio position valuation, 0.05 INR price tick rounding,
IST trading session validation, and microkernel plugin binding.
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

MAGIC_NUMBER_STOCKMART: int = 9100066


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


class StockMartEngine:
    """
    StockMart Orderbook & Portfolio Management Engine.
    """

    def __init__(self, initial_cash: float = 1000000.0) -> None:
        self.cash = initial_cash
        self.magic_number = MAGIC_NUMBER_STOCKMART
        self.bids: List[Dict[str, Any]] = []
        self.asks: List[Dict[str, Any]] = []
        self.positions: Dict[str, int] = {}

    def add_limit_order(self, symbol: str, side: str, price: float, quantity: int) -> Dict[str, Any]:
        """
        Adds a limit order to the bid/ask orderbook and attempts matching.
        """
        price = round_tick_005(price)
        quantity = max(1, quantity)
        side = side.upper()

        order = {
            "symbol": symbol.upper(),
            "side": side,
            "price": price,
            "quantity": quantity,
            "filled": 0,
            "id": f"ORD-{int(datetime.now().timestamp() * 1000)}",
        }

        if side == "BUY":
            self.bids.append(order)
            self.bids.sort(key=lambda x: x["price"], reverse=True)
        else:
            self.asks.append(order)
            self.asks.sort(key=lambda x: x["price"])

        matched_trades = self._match_orderbook()

        return {
            "order_id": order["id"],
            "matched_trades": matched_trades,
            "bids_count": len(self.bids),
            "asks_count": len(self.asks),
            "magic_number": self.magic_number,
        }

    def _match_orderbook(self) -> List[Dict[str, Any]]:
        trades = []
        while self.bids and self.asks and self.bids[0]["price"] >= self.asks[0]["price"]:
            top_bid = self.bids[0]
            top_ask = self.asks[0]

            exec_qty = min(top_bid["quantity"] - top_bid["filled"], top_ask["quantity"] - top_ask["filled"])
            exec_price = top_ask["price"]

            top_bid["filled"] += exec_qty
            top_ask["filled"] += exec_qty

            trade = {
                "symbol": top_bid["symbol"],
                "price": exec_price,
                "quantity": exec_qty,
                "buy_order": top_bid["id"],
                "sell_order": top_ask["id"],
            }
            trades.append(trade)

            if top_bid["filled"] >= top_bid["quantity"]:
                self.bids.pop(0)
            if top_ask["filled"] >= top_ask["quantity"]:
                self.asks.pop(0)

        return trades

    def evaluate_portfolio_equity(self, current_prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Calculates total portfolio equity across positions and cash.
        """
        position_value = 0.0
        for symbol, qty in self.positions.items():
            price = current_prices.get(symbol, 0.0)
            position_value += qty * price

        total_equity = self.cash + position_value
        return {
            "cash": round(self.cash, 2),
            "position_value": round(position_value, 2),
            "total_equity": round(total_equity, 2),
            "magic_number": self.magic_number,
        }


class StockMartBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for StockMart Engine.
    """

    def __init__(self, broker_name: str = "STOCKMART") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = StockMartEngine()

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
        qty = round_to_indian_quantity(request.quantity)

        res = self.engine.add_limit_order(
            symbol=request.symbol,
            side=request.order_type,
            price=sanitized_price,
            quantity=qty,
        )

        return SEBIOrderResponse(
            success=True,
            ticket=res["order_id"],
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
        return {"balance": self.engine.cash, "equity": self.engine.cash, "currency": "INR", "is_demo": True}

    def get_history(self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute") -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 500.0, "ask": 500.15, "last": 500.05}

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


# Register in microkernel plugin registry
IndianBrokerPluginRegistry.register("STOCKMART", StockMartBrokerAdapter)
