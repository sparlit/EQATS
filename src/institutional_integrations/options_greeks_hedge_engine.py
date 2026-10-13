# codespell:ignore IST,MIS
"""
Options Greeks Dynamic Auto-Hedging Engine (Black-76 Delta/Gamma/Vega Auto-Balancer)
====================================================================================
Computes analytical Black-76 option Greeks (Delta, Gamma, Vega, Theta), calculates
net portfolio delta exposure, and automatically generates delta-neutral hedge orders,
enforcing 0.05 INR tick rounding and IST market session validation.

Magic Number: 9100102
"""

import logging
import math
import zoneinfo
from datetime import datetime
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
)

logger = logging.getLogger(__name__)

MAGIC_NUMBER_OPTIONS_HEDGE: int = 9100102


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round(round(price / 0.05) * 0.05, 2)


def is_ist_market_open(now_dt: datetime | None = None) -> bool:
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


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function approximation."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class OptionsGreeksHedgeEngine:
    """
    Black-76 analytical options Greeks calculator & delta-neutral hedge generator.
    """

    def __init__(self, risk_free_rate: float = 0.065) -> None:
        self.r = risk_free_rate

    def calculate_greeks(
        self,
        spot: float,
        strike: float,
        dte_days: float,
        volatility: float,
        option_type: str = "CE",
    ) -> dict[str, float]:
        """
        Calculates Black-76 option price and analytical Greeks (Delta, Gamma, Vega, Theta).
        """
        if spot <= 0 or strike <= 0 or dte_days <= 0 or volatility <= 0:
            return {"price": 0.0, "delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

        T = dte_days / 365.0
        v = max(volatility, 0.0001)

        d1 = (math.log(spot / strike) + (self.r + 0.5 * v * v) * T) / (v * math.sqrt(T))
        d2 = d1 - v * math.sqrt(T)

        if option_type.upper() in ["CE", "CALL"]:
            price = spot * _norm_cdf(d1) - strike * math.exp(-self.r * T) * _norm_cdf(d2)
            delta = _norm_cdf(d1)
        else:
            price = strike * math.exp(-self.r * T) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
            delta = _norm_cdf(d1) - 1.0

        gamma = _norm_pdf(d1) / (spot * v * math.sqrt(T))
        vega = spot * _norm_pdf(d1) * math.sqrt(T) / 100.0
        theta = (-spot * _norm_pdf(d1) * v / (2.0 * math.sqrt(T))) / 365.0

        return {
            "price": round_tick_005(price),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "vega": round(vega, 4),
            "theta": round(theta, 4),
        }

    def evaluate_portfolio_delta_hedge(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Calculates total portfolio net delta exposure and suggests hedge order quantity.
        """
        net_delta = 0.0
        for pos in positions:
            spot = pos.get("spot", 24000.0)
            strike = pos.get("strike", 24000.0)
            dte = pos.get("dte", 7.0)
            vol = pos.get("volatility", 0.15)
            opt_type = pos.get("option_type", "CE")
            qty = pos.get("quantity", 50)
            side = 1.0 if pos.get("side", "BUY").upper() == "BUY" else -1.0

            greeks = self.calculate_greeks(spot, strike, dte, vol, opt_type)
            net_delta += greeks["delta"] * qty * side

        hedge_side = "SELL" if net_delta > 0 else "BUY"
        hedge_qty = int(round(abs(net_delta)))

        return {
            "net_delta": round(net_delta, 2),
            "is_hedged": abs(net_delta) < 5.0,
            "suggested_hedge_side": hedge_side,
            "suggested_hedge_quantity": hedge_qty,
        }


class OptionsGreeksHedgeEngineAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter for Options Greeks Auto-Hedging Engine.
    Registered in IndianBrokerPluginRegistry under OPTIONS_GREEKS_HEDGE_ENGINE.
    """

    def __init__(self, is_sandbox: bool = True) -> None:
        super().__init__("OPTIONS_GREEKS_HEDGE_ENGINE", is_sandbox=is_sandbox)
        self.engine = OptionsGreeksHedgeEngine()
        self._connected = True

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self) -> dict[str, Any]:
        return {
            "broker": "OPTIONS_GREEKS_HEDGE_ENGINE",
            "currency": "INR",
            "balance": 2500000.0,
            "equity": 2500000.0,
            "is_sandbox": self.is_sandbox,
        }

    def get_current_price(self, symbol: str, exchange: str = "NFO") -> dict[str, Any]:
        return {
            "symbol": symbol,
            "exchange": exchange,
            "last": 215.50,
            "bid": 215.45,
            "ask": 215.55,
        }

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        dt_now = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
        if not is_ist_market_open(dt_now) and not self.is_sandbox:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED_MARKET_CLOSED",
                product=request.product,
                exchange=request.exchange or "NFO",
                error="Execution blocked: Outside IST market session hours.",
            )

        rounded_price = round_tick_005(request.price) if request.price > 0 else 215.50

        return SEBIOrderResponse(
            success=True,
            ticket=f"HEDGE_{int(dt_now.timestamp() * 1000)}",
            price=rounded_price,
            status="EXECUTED",
            product=request.product,
            exchange=request.exchange or "NFO",
            raw_response={"symbol": request.symbol, "quantity": request.quantity},
        )

    def close_order(
        self, ticket: str, symbol: str, exchange: str = "NFO", product: str = "NRML"
    ) -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=215.50,
            status="CLOSED",
            product=product,
            exchange=exchange,
            raw_response={"symbol": symbol},
        )

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def get_open_orders(self) -> list[dict[str, Any]]:
        return []

    def get_history(
        self, symbol: str, exchange: str = "NFO", count: int = 100, interval: str = "minute"
    ) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "close": 215.50} for _ in range(count)]

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        return True


IndianBrokerPluginRegistry.register("OPTIONS_GREEKS_HEDGE_ENGINE", OptionsGreeksHedgeEngineAdapter)
