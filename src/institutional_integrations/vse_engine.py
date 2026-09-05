"""
Virtual Stock Exchange (VSE) Engine Integration Module
======================================================
Adapts Virtual Demat account portfolio management, buy/sell simulated trade execution,
total investment tracking, and unrealized/realized PnL accounting from `aneesh540/vse`.

Magic Number: 9100038
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import zoneinfo

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    IndianBrokerPluginRegistry,
)

logger = logging.getLogger(__name__)

MAGIC_NUMBER_VSE: int = 9100038


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round(round(price / 0.05) * 0.05, 2)


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


class VirtualDematAccount:
    """
    Virtual Demat account holding manager and simulated execution accounting core.
    Tracks holdings, average buy price, total invested capital, realized PnL, and cash balance.
    """

    def __init__(self, username: str = "virtual_trader", initial_cash: float = 1000000.0) -> None:
        self.username = username
        self.magic_number = MAGIC_NUMBER_VSE
        self.cash_balance = initial_cash
        self.initial_capital = initial_cash
        self.holdings: Dict[str, Dict[str, Any]] = {}
        self.total_invested: float = 0.0
        self.realized_pnl: float = 0.0

    def buy_share(self, symbol: str, quantity: int, price: float) -> Dict[str, Any]:
        """
        Executes simulated share purchase and updates Demat portfolio holdings.
        """
        symbol = symbol.upper().strip()
        rounded_price = round_tick_005(price)
        cost = rounded_price * quantity

        if cost > self.cash_balance:
            return {
                "success": False,
                "reason": f"INSUFFICIENT_FUNDS_REQUIRED_{cost:.2f}_AVAILABLE_{self.cash_balance:.2f}",
            }

        self.cash_balance -= cost
        self.total_invested += cost

        if symbol in self.holdings:
            existing = self.holdings[symbol]
            new_qty = existing["quantity"] + quantity
            new_total_cost = (existing["avg_price"] * existing["quantity"]) + cost
            existing["quantity"] = new_qty
            existing["avg_price"] = round_tick_005(new_total_cost / new_qty)
        else:
            self.holdings[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": rounded_price,
            }

        return {
            "success": True,
            "symbol": symbol,
            "action": "BUY",
            "quantity": quantity,
            "price": rounded_price,
            "cost": cost,
            "remaining_cash": self.cash_balance,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }

    def sell_share(self, symbol: str, quantity: int, price: float) -> Dict[str, Any]:
        """
        Executes simulated share sale and records realized gain/loss.
        """
        symbol = symbol.upper().strip()
        rounded_price = round_tick_005(price)

        if symbol not in self.holdings or self.holdings[symbol]["quantity"] < quantity:
            avail = self.holdings.get(symbol, {}).get("quantity", 0)
            return {
                "success": False,
                "reason": f"INSUFFICIENT_HOLDINGS_REQUESTED_{quantity}_AVAILABLE_{avail}",
            }

        holding = self.holdings[symbol]
        avg_buy_price = holding["avg_price"]
        proceeds = rounded_price * quantity
        cost_basis = avg_buy_price * quantity
        pnl = round(proceeds - cost_basis, 2)

        self.cash_balance += proceeds
        self.realized_pnl += pnl
        self.total_invested -= cost_basis

        holding["quantity"] -= quantity
        if holding["quantity"] == 0:
            del self.holdings[symbol]

        return {
            "success": True,
            "symbol": symbol,
            "action": "SELL",
            "quantity": quantity,
            "price": rounded_price,
            "pnl": pnl,
            "remaining_cash": self.cash_balance,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }

    def get_portfolio_summary(
        self, current_prices: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Calculates portfolio market value and total unrealized/realized PnL.
        """
        current_prices = current_prices or {}
        market_value = 0.0
        unrealized_pnl = 0.0

        holdings_summary = []
        for symbol, holding in self.holdings.items():
            curr_p = current_prices.get(symbol, holding["avg_price"])
            val = curr_p * holding["quantity"]
            u_pnl = (curr_p - holding["avg_price"]) * holding["quantity"]

            market_value += val
            unrealized_pnl += u_pnl

            holdings_summary.append({
                "symbol": symbol,
                "quantity": holding["quantity"],
                "avg_price": holding["avg_price"],
                "current_price": curr_p,
                "market_value": round(val, 2),
                "unrealized_pnl": round(u_pnl, 2),
            })

        total_net_worth = round(self.cash_balance + market_value, 2)

        return {
            "username": self.username,
            "cash_balance": round(self.cash_balance, 2),
            "market_value": round(market_value, 2),
            "total_net_worth": total_net_worth,
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_return_pct": round(((total_net_worth - self.initial_capital) / self.initial_capital) * 100.0, 2),
            "holdings": holdings_summary,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }


class VSEBrokerAdapter(SEBIBrokerAdapter):
    """
    Broker Adapter plugin for Virtual Stock Exchange (VSE) Engine.
    """

    def __init__(self, broker_name: str = "VSEBroker") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.demat = VirtualDematAccount()
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        self._connected = True
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return self.demat.get_portfolio_summary()

    def get_history(
        self, symbol: str, timeframe: str = "1d", limit: int = 100
    ) -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 100.0, "ask": 100.05, "last_price": 100.0}

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                instrument_token=0,
                error="Broker adapter not connected",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                instrument_token=0,
                error="Market is closed (Outside IST trading hours)",
            )

        rounded_price = round_tick_005(request.price)
        qty = int(request.quantity)

        if request.order_type.upper() == "BUY":
            res = self.demat.buy_share(request.symbol, qty, rounded_price)
        else:
            res = self.demat.sell_share(request.symbol, qty, rounded_price)

        if not res["success"]:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=rounded_price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                instrument_token=0,
                error=res.get("reason", "Order execution failed"),
            )

        return SEBIOrderResponse(
            success=True,
            ticket=f"VSE-{int(datetime.now().timestamp()*1000)}",
            price=rounded_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
            instrument_token=10006,
            error="",
        )

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        return True

    def close_order(
        self, ticket: str, symbol: str = "", exchange: str = "NSE"
    ) -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CANCELLED",
            product="MIS",
            exchange=exchange,
            instrument_token=0,
            error="",
        )

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


# Register plugin in IndianBrokerPluginRegistry on import
IndianBrokerPluginRegistry.register("VSE_DEMAT", VSEBrokerAdapter)
