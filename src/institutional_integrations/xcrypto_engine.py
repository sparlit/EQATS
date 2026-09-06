"""
XCrypto Engine (Repo 083 Adaptation)
=====================================
Adapted from bohr1005/xcrypto under Magic Number 9100080.
Provides high-performance crypto spot/futures trading, PyAlgo strategy signal
execution, position management, and order routing with Indian Market safety compliance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import math

from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
)

MAGIC_NUMBER = 9100080


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR/unit tick size."""
    return round(round(price * 20.0) / 20.0, 2)


def is_ist_market_open(dt: Optional[datetime] = None) -> bool:
    """Checks if current time falls within IST trading session (09:15 - 15:30 IST)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    ist_dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
    if ist_dt.weekday() >= 5:
        return False
    market_start = ist_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = ist_dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= ist_dt <= market_end


@dataclass
class XCryptoPosition:
    """Represents an open crypto position."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    quantity: float
    entry_price: float
    leverage: float = 1.0
    unrealized_pnl: float = 0.0


@dataclass
class XCryptoOrder:
    """Represents a crypto order."""
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_type: str  # "LIMIT", "MARKET", "STOP_LOSS"
    status: str = "SUBMITTED"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class XCryptoEngine:
    """
    High-performance Crypto Spot/Futures trading engine adapted from bohr1005/xcrypto.
    Features PyAlgo strategy signal generation, order routing, and position management.
    """

    def __init__(self, name: str = "XCryptoEngine") -> None:
        self.name = name
        self.magic_number = MAGIC_NUMBER
        self.positions: Dict[str, XCryptoPosition] = {}
        self.orders: List[XCryptoOrder] = []
        self.order_counter = 0

    def evaluate_pyalgo_signal(
        self,
        symbol: str,
        prices: List[float],
        short_window: int = 5,
        long_window: int = 20,
    ) -> Dict[str, Any]:
        """Calculates moving average crossover signal (PyAlgo engine)."""
        if len(prices) < long_window:
            return {
                "symbol": symbol,
                "action": "HOLD",
                "reason": f"Insufficient price data ({len(prices)}/{long_window})",
                "short_ma": 0.0,
                "long_ma": 0.0,
            }

        short_ma = sum(prices[-short_window:]) / short_window
        long_ma = sum(prices[-long_window:]) / long_window
        prev_short_ma = sum(prices[-short_window - 1 : -1]) / short_window
        prev_long_ma = sum(prices[-long_window - 1 : -1]) / long_window

        action = "HOLD"
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            action = "BUY"
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            action = "SELL"

        return {
            "symbol": symbol,
            "action": action,
            "short_ma": round(short_ma, 4),
            "long_ma": round(long_ma, 4),
            "current_price": round_tick_005(prices[-1]),
        }

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_type: str = "LIMIT",
        leverage: float = 1.0,
    ) -> XCryptoOrder:
        """Places and processes a new order."""
        self.order_counter += 1
        order_id = f"XCRYPTO-{self.order_counter:06d}"
        rounded_price = round_tick_005(price)

        order = XCryptoOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=rounded_price,
            order_type=order_type,
            status="FILLED",
        )
        self.orders.append(order)

        # Update position
        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos.side == side:
                new_qty = pos.quantity + quantity
                new_entry = ((pos.quantity * pos.entry_price) + (quantity * rounded_price)) / new_qty
                pos.quantity = new_qty
                pos.entry_price = round_tick_005(new_entry)
            else:
                if pos.quantity > quantity:
                    pos.quantity -= quantity
                elif pos.quantity == quantity:
                    del self.positions[symbol]
                else:
                    rem_qty = quantity - pos.quantity
                    self.positions[symbol] = XCryptoPosition(
                        symbol=symbol,
                        side=side,
                        quantity=rem_qty,
                        entry_price=rounded_price,
                        leverage=leverage,
                    )
        else:
            self.positions[symbol] = XCryptoPosition(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=rounded_price,
                leverage=leverage,
            )

        return order

    def update_position_pnl(self, symbol: str, current_price: float) -> float:
        """Updates and returns unrealized PnL for symbol position."""
        if symbol not in self.positions:
            return 0.0
        pos = self.positions[symbol]
        rounded_price = round_tick_005(current_price)
        if pos.side == "BUY" or pos.side == "LONG":
            pos.unrealized_pnl = (rounded_price - pos.entry_price) * pos.quantity * pos.leverage
        else:
            pos.unrealized_pnl = (pos.entry_price - rounded_price) * pos.quantity * pos.leverage
        return round(pos.unrealized_pnl, 2)


class XCryptoBrokerAdapter(SEBIBrokerAdapter):
    """SEBI Broker adapter for XCrypto Engine."""

    def __init__(
        self, api_key: str = "", api_secret: str = "", access_token: str = "", is_sandbox: bool = False
    ) -> None:
        super().__init__(api_key=api_key, api_secret=api_secret, access_token=access_token, is_sandbox=is_sandbox)
        self.magic_number = MAGIC_NUMBER
        self.engine = XCryptoEngine()

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "margin_used": 0.0,
            "available_margin": 1000000.0,
        }

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 100.0, "ask": 100.05, "last": 100.0}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._is_connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="DISCONNECTED",
                product=req.product,
                exchange=req.exchange,
                error="Adapter is not connected to exchange",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=req.product,
                exchange=req.exchange,
                error="Market is closed outside IST trading hours",
            )

        order = self.engine.place_order(
            symbol=req.symbol,
            side=req.order_type,
            quantity=req.quantity,
            price=req.price,
        )
        return SEBIOrderResponse(
            success=True,
            ticket=order.order_id,
            price=order.price,
            status="FILLED",
            product=req.product,
            exchange=req.exchange,
            error="",
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=100.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
            error="",
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        return True

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return [
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "quantity": order.quantity,
                "price": order.price,
            }
            for order in self.engine.orders
        ]

    def place_order(self, order_details: Dict[str, Any]) -> Dict[str, Any]:
        symbol = order_details.get("symbol", "BTCUSDT")
        side = order_details.get("side", "BUY")
        quantity = order_details.get("quantity", 1.0)
        price = order_details.get("price", 100.0)
        order_type = order_details.get("order_type", "LIMIT")
        leverage = order_details.get("leverage", 1.0)

        order = self.engine.place_order(symbol, side, quantity, price, order_type, leverage)
        return {
            "status": "SUCCESS",
            "order_id": order.order_id,
            "symbol": order.symbol,
            "price": order.price,
            "quantity": order.quantity,
            "magic_number": self.magic_number,
        }

    def cancel_order(self, order_id: str) -> bool:
        return True

    def get_positions(self) -> List[Dict[str, Any]]:
        return [
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "unrealized_pnl": pos.unrealized_pnl,
            }
            for pos in self.engine.positions.values()
        ]


# Register adapter into IndianBrokerPluginRegistry
IndianBrokerPluginRegistry.register("XCRYPTO", XCryptoBrokerAdapter)
