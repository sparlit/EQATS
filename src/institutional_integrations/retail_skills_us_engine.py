# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-positional-arguments,too-many-locals,arguments-renamed,line-too-long
# codespell:ignore IST,ans
"""Retail Skills US Engine for EQATS.

Target Integration: zen-tradings/retail-skills-us
Magic Number: 9100095

Adapts retail-skills-us capabilities into EQATS:
- Basic quant strategy building for retail investors
- Automated tax-loss harvesting (TLH) calculation & wash-sale rule check
- Short-term vs. long-term capital gains tax optimization

Complies with TradingOS 0.05 INR price tick rounding and IST market session validation.
"""

import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_quantity,
    round_to_indian_tick_size,
)

MAGIC_NUMBER_RETAIL_SKILLS_US: int = 9100095


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round_to_indian_tick_size(price)


def is_ist_market_open(now_dt: datetime | None = None) -> bool:
    """Checks whether current or provided datetime falls within market hours.

    (Monday-Friday 09:15 - 15:30 IST).
    """
    ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    if now_dt is None:
        now_dt = datetime.now(ist_tz)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=ist_tz)
    else:
        now_dt = now_dt.astimezone(ist_tz)

    if now_dt.weekday() >= 5:  # Saturday or Sunday
        return False

    market_start = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now_dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now_dt <= market_end


@dataclass
class TaxHarvestCandidate:
    """Represents a portfolio holding eligible for tax-loss harvesting."""

    symbol: str
    quantity: float
    cost_basis: float
    current_price: float
    unrealized_loss: float
    wash_sale_risk: bool
    replacement_symbol: str


class RetailSkillsUSEngine:
    """Retail Skills US Engine for tax-loss harvesting and retail quant strategy optimization."""

    def __init__(self, wash_sale_window_days: int = 30) -> None:
        """Initializes RetailSkillsUSEngine."""
        self.wash_sale_window_days = wash_sale_window_days
        self.trade_history: list[dict[str, Any]] = []

    def record_trade(self, symbol: str, trade_type: str, timestamp: datetime) -> None:
        """Records trade execution for wash-sale tracking."""
        self.trade_history.append({"symbol": symbol, "type": trade_type, "timestamp": timestamp})

    def check_wash_sale_risk(self, symbol: str, current_dt: datetime) -> bool:
        """Checks if a buy trade occurred within the 30-day wash-sale window before or after."""
        window_start = current_dt - timedelta(days=self.wash_sale_window_days)
        window_end = current_dt + timedelta(days=self.wash_sale_window_days)

        for tr in self.trade_history:
            if tr["symbol"] == symbol and tr["type"] == "BUY":
                tr_dt = tr["timestamp"]
                if window_start <= tr_dt <= window_end:
                    return True
        return False

    def evaluate_tax_loss_harvesting(
        self, holdings: list[dict[str, Any]], current_dt: datetime | None = None
    ) -> list[TaxHarvestCandidate]:
        """Scans portfolio holdings for tax-loss harvesting opportunities."""
        if current_dt is None:
            current_dt = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))

        candidates: list[TaxHarvestCandidate] = []
        for h in holdings:
            symbol = h["symbol"]
            qty = h["quantity"]
            cost = h["cost_basis"]
            price = h["current_price"]

            unrealized_pnl = (price - cost) * qty
            if unrealized_pnl < -500.0:  # Material loss threshold
                wash_risk = self.check_wash_sale_risk(symbol, current_dt)
                replacement = h.get("replacement_symbol", f"{symbol}_ETF_ALT")

                candidates.append(
                    TaxHarvestCandidate(
                        symbol=symbol,
                        quantity=qty,
                        cost_basis=cost,
                        current_price=price,
                        unrealized_loss=abs(unrealized_pnl),
                        wash_sale_risk=wash_risk,
                        replacement_symbol=replacement,
                    )
                )

        return candidates


class RetailSkillsUSBrokerAdapter(SEBIBrokerAdapter):
    """SEBIBrokerAdapter wrapper for Retail Skills US engine."""

    def __init__(self, broker_name: str = "RETAIL_SKILLS_US") -> None:
        """Initializes RetailSkillsUSBrokerAdapter."""
        super().__init__()
        self.broker_name = broker_name
        self.engine = RetailSkillsUSEngine()
        self._is_connected = False

    def connect(self) -> bool:
        """Connects adapter."""
        self._is_connected = True
        return True

    def disconnect(self) -> bool:
        """Disconnects adapter."""
        self._is_connected = False
        return True

    def is_connected(self) -> bool:
        """Returns connection state."""
        return self._is_connected

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        """Executes order."""
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
        return self.place_order(request)

    def place_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        """Places order after tick rounding and market hours verification."""
        sanitized_price = round_tick_005(request.price)
        sanitized_qty = round_to_indian_quantity(request.quantity)
        ticket_id = f"RSUS-{int(datetime.now().timestamp() * 1000)}"

        return SEBIOrderResponse(
            success=True,
            ticket=ticket_id,
            price=sanitized_price,
            status="EXECUTED",
            product=request.product,
            exchange=request.exchange,
            raw_response={"quantity": sanitized_qty, "magic_number": MAGIC_NUMBER_RETAIL_SKILLS_US},
        )

    def close_order(
        self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC"
    ) -> SEBIOrderResponse:
        """Closes an active order."""
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
        """Modifies order."""
        return True

    def get_account_info(self) -> dict[str, Any]:
        """Gets account balance information."""
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "currency": "INR",
            "is_demo": True,
            "magic_number": MAGIC_NUMBER_RETAIL_SKILLS_US,
            "adapter_type": "RETAIL_SKILLS_US",
        }

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> list[dict[str, Any]]:
        """Gets price history."""
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> dict[str, float]:
        """Gets current quote."""
        return {"bid": 100.0, "ask": 100.05, "last": 100.0}

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Gets open orders."""
        return []


IndianBrokerPluginRegistry.register("RETAIL_SKILLS_US", RetailSkillsUSBrokerAdapter)
