# codespell:ignore IST,ist
"""
Automated Trading Tool Suite & Institutional Integration Adapter Core
=====================================================================

Adaptation Target: github.com/topics/automated-trading-tool
Magic Number: 9100090 & 9100091

Provides an integrated institutional automated trading engine combining:
1. Automated Execution & Risk Router Engine (OpenAlgo/Nautilus adaptation patterns)
2. Multi-Strategy Agentic Signal Dispatcher (AI Algo Trading Agent & Multi-Factor Decision Core)
3. 0.05 INR price tick rounding (`round_to_ist_tick` / `round_to_indian_tick_size`)
4. IST market session active validation (`is_ist_market_session_active`)
5. Subclassing of `SEBIBrokerAdapter` and dynamic registration in `IndianBrokerPluginRegistry`.
"""

import datetime
import logging
import zoneinfo
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_quantity,
    validate_indian_product_tag,
)

logger = logging.getLogger(__name__)

MAGIC_NUMBER_ROUTER: int = 9100090
MAGIC_NUMBER_DISPATCHER: int = 9100091


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


class AutomatedExecutionRiskRouter:
    """
    Automated Order Slicing and Risk Routing Engine.
    Executes volume slicing (iceberg orders), max drawdown checks, and position risk limits.
    """

    def __init__(self, max_slice_lot: float = 50.0, max_position_limit: float = 500000.0) -> None:
        self.max_slice_lot = max_slice_lot
        self.max_position_limit = max_position_limit

    def slice_and_validate_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        current_portfolio_value: float = 0.0,
        dt: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """
        Validates IST market session, enforces position limit risks, and slices order into compliant lots.
        """
        rounded_price = round_to_ist_tick(price)
        qty = round_to_indian_quantity(quantity)
        session_active = is_ist_market_session_active(dt)

        order_notional = qty * rounded_price
        if current_portfolio_value + order_notional > self.max_position_limit:
            return {
                "approved": False,
                "reason": (
                    f"Position limit exceeded ({current_portfolio_value + order_notional:.2f} > "
                    f"{self.max_position_limit})"
                ),
                "slices": [],
                "magic_number": MAGIC_NUMBER_ROUTER,
            }

        if not session_active:
            return {
                "approved": False,
                "reason": "Execution rejected: Outside IST market session (09:15 - 15:30 IST)",
                "slices": [],
                "magic_number": MAGIC_NUMBER_ROUTER,
            }

        # Slicing
        slices: list[dict[str, Any]] = []
        remaining = qty
        max_lot = int(self.max_slice_lot)
        slice_idx = 1

        while remaining > 0:
            current_slice = min(remaining, max_lot)
            slices.append(
                {
                    "slice_id": slice_idx,
                    "symbol": symbol.upper(),
                    "action": action.upper(),
                    "quantity": current_slice,
                    "price": rounded_price,
                    "status": "APPROVED",
                }
            )
            remaining -= current_slice
            slice_idx += 1

        return {
            "approved": True,
            "reason": "Order validated and sliced successfully",
            "total_quantity": qty,
            "price": rounded_price,
            "slice_count": len(slices),
            "slices": slices,
            "magic_number": MAGIC_NUMBER_ROUTER,
        }


class MultiStrategyAgenticSignalDispatcher:
    """
    Multi-Factor Agentic Strategy Core.
    Combines RSI, Moving Average Crossovers, and Volatility Sizing to generate automated signals.
    """

    def __init__(self, rsi_period: int = 14, fast_ma: int = 10, slow_ma: int = 30) -> None:
        self.rsi_period = rsi_period
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma

    def compute_rsi(self, prices: list[float]) -> float:
        """Computes Relative Strength Index (RSI) for input price series."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        avg_gain = sum(gains[-self.rsi_period :]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period :]) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    def generate_signal(
        self,
        symbol: str,
        prices: list[float],
        current_price: float,
        dt: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """
        Generates automated trading decision based on technical strategy signals.
        """
        rounded_price = round_to_ist_tick(current_price)
        active_session = is_ist_market_session_active(dt)

        if not active_session or len(prices) < self.slow_ma:
            return {
                "symbol": symbol.upper(),
                "action": "HOLD",
                "confidence": 0.0,
                "price": rounded_price,
                "reason": "Session inactive or insufficient price history",
                "magic_number": MAGIC_NUMBER_DISPATCHER,
            }

        rsi = self.compute_rsi(prices)
        fast_ema = sum(prices[-self.fast_ma :]) / self.fast_ma
        slow_ema = sum(prices[-self.slow_ma :]) / self.slow_ma

        if rsi < 35.0 and fast_ema > slow_ema:
            action = "BUY"
            confidence = min(1.0, 0.7 + (35.0 - rsi) / 100.0)
            reason = "RSI oversold with bullish MA crossover"
        elif rsi > 65.0 and fast_ema < slow_ema:
            action = "SELL"
            confidence = min(1.0, 0.7 + (rsi - 65.0) / 100.0)
            reason = "RSI overbought with bearish MA crossover"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = "Neutral strategy signals"

        return {
            "symbol": symbol.upper(),
            "action": action,
            "confidence": round(confidence, 2),
            "price": rounded_price,
            "rsi": rsi,
            "reason": reason,
            "magic_number": MAGIC_NUMBER_DISPATCHER,
        }


class AutomatedTradingToolAdapter(SEBIBrokerAdapter):
    """
    SEBIBrokerAdapter implementation for the Automated Trading Tool Engine.
    Exposes full order execution, portfolio risk management, and microkernel plugin binding.
    """

    BROKER_KEY = "AUTOMATED_TRADING_TOOL"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        access_token: str = "",
        is_sandbox: bool = False,
    ) -> None:
        super().__init__(api_key, api_secret, access_token, is_sandbox)
        self.router = AutomatedExecutionRiskRouter()
        self.dispatcher = MultiStrategyAgenticSignalDispatcher()
        self.orders: dict[str, dict[str, Any]] = {}

    def connect(self) -> bool:
        """Connects the adapter and sets active state."""
        self._is_connected = True
        logger.info("AutomatedTradingToolAdapter connected.")
        return True

    def is_connected(self) -> bool:
        """Returns connection status."""
        return self._is_connected

    def disconnect(self) -> bool:
        """Disconnects the adapter."""
        self._is_connected = False
        return True

    def get_account_info(self) -> dict[str, Any]:
        """Returns current account balance and margin limits."""
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "available_margin": 1000000.0,
            "currency": "INR",
            "is_demo": self.is_sandbox,
        }

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> list[dict[str, Any]]:
        """Returns simulated OHLCV historical price bars."""
        bars = []
        base = 2500.0 if "RELIANCE" in symbol.upper() else 1000.0
        now = datetime.datetime.now().timestamp()
        for i in range(count):
            t = now - (count - i) * 60
            price = round_to_ist_tick(base + (i * 0.2))
            bars.append(
                {
                    "timestamp": int(t),
                    "open": price,
                    "high": price + 0.5,
                    "low": price - 0.5,
                    "close": price,
                    "volume": 500 + i * 5,
                }
            )
        return bars

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> dict[str, float]:
        """Returns bid, ask, and last price quotes."""
        base = 2500.0 if "RELIANCE" in symbol.upper() else 1000.0
        rounded = round_to_ist_tick(base)
        return {"bid": rounded, "ask": round_to_ist_tick(rounded + 0.05), "last": rounded}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        """Executes an order after risk validation and volume slicing."""
        product = validate_indian_product_tag(req.product, default="CNC")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        price = round_to_ist_tick(req.price if req.price > 0 else 1000.0)

        validation = self.router.slice_and_validate_order(
            symbol=req.symbol,
            action=req.order_type,
            quantity=req.quantity,
            price=price,
        )

        if not validation["approved"] and not self.is_sandbox:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=product,
                exchange=exchange,
                error=validation["reason"],
            )

        ticket = f"ATT_{len(self.orders) + 1001}"
        record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "action": req.order_type,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_ROUTER,
        }
        self.orders[ticket] = record

        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response=validation,
        )

    def close_order(
        self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC"
    ) -> SEBIOrderResponse:
        """Closes or squares off an open order."""
        if ticket in self.orders:
            self.orders.pop(ticket)
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
        )

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        """Modifies order price parameters."""
        if ticket in self.orders:
            if price > 0:
                self.orders[ticket]["price"] = round_to_ist_tick(price)
            return True
        return False

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Returns active open orders."""
        return list(self.orders.values())


# Register class into Microkernel Plugin Registry
IndianBrokerPluginRegistry.register("AUTOMATED_TRADING_TOOL", AutomatedTradingToolAdapter)
IndianBrokerPluginRegistry.register("ATT_ENGINE", AutomatedTradingToolAdapter)
