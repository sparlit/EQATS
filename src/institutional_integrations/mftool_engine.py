# codespell:ignore IST,MIS
"""
Indian Mutual Fund NAV, Asset Allocation & Scheme Analytics Engine (mftool adaptation)
========================================================================================
Provides mutual fund scheme search, NAV performance history analytics, risk-adjusted returns
(Sharpe ratio, CAGR, max drawdown), asset allocation matrix analysis, 0.05 INR price tick
rounding, and IST market session safeguards.

Adapted from: nayakwadis/mftool
Magic Number: 9100103
"""

import logging
import math
import zoneinfo
from datetime import datetime, timezone
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
)

logger = logging.getLogger(__name__)

MAGIC_NUMBER_MFTOOL: int = 9100103


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round(round(price / 0.05) * 0.05, 2)


def validate_ist_market_session(dt: datetime | None = None) -> bool:
    """
    Validates if current or provided datetime falls within Indian Standard Time (IST)
    trading hours (09:15 to 15:30 IST, Monday to Friday).
    """
    if dt is None:
        dt = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(zoneinfo.ZoneInfo("Asia/Kolkata"))

    if dt.weekday() in (5, 6):
        return False

    start_time = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = dt.replace(hour=15, minute=30, second=0, microsecond=0)

    return start_time <= dt <= end_time


class MFToolEngine:
    """
    Mutual fund scheme analytics, NAV performance calculation, and portfolio asset allocation engine.
    """

    def __init__(self, risk_free_rate: float = 0.065) -> None:
        self.risk_free_rate = risk_free_rate
        self._scheme_codes: dict[str, str] = {
            "100027": "Nippon India Small Cap Fund - Growth",
            "100033": "Axis Bluechip Fund - Direct Plan - Growth",
            "100041": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "100052": "SBI Small Cap Fund - Direct Plan - Growth",
            "100064": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
        }

    def search_schemes(self, query: str) -> dict[str, str]:
        """
        Searches available mutual fund scheme codes matching the query string.
        """
        q = query.lower()
        return {code: name for code, name in self._scheme_codes.items() if q in name.lower()}

    def calculate_nav_metrics(self, nav_series: list[float], period_years: float = 1.0) -> dict[str, float]:
        """
        Computes CAGR, annual volatility, Max Drawdown, and Sharpe Ratio from a historical NAV series.
        """
        if not nav_series or len(nav_series) < 2:
            return {
                "cagr": 0.0,
                "volatility": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "current_nav": 0.0,
            }

        start_nav = nav_series[0]
        end_nav = nav_series[-1]
        current_nav = round_tick_005(end_nav)

        # CAGR
        if start_nav > 0 and period_years > 0:
            cagr = ((end_nav / start_nav) ** (1.0 / period_years)) - 1.0
        else:
            cagr = 0.0

        # Daily Returns & Volatility
        returns = [(nav_series[i] - nav_series[i - 1]) / nav_series[i - 1] for i in range(1, len(nav_series))]
        mean_ret = sum(returns) / len(returns) if returns else 0.0
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns) if returns else 0.0
        daily_vol = math.sqrt(variance)
        ann_volatility = daily_vol * math.sqrt(252)

        # Max Drawdown
        peak = nav_series[0]
        max_dd = 0.0
        for nav in nav_series:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Sharpe Ratio
        if ann_volatility > 0:
            sharpe = (cagr - self.risk_free_rate) / ann_volatility
        else:
            sharpe = 0.0

        return {
            "cagr": round(cagr, 4),
            "volatility": round(ann_volatility, 4),
            "max_drawdown": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 4),
            "current_nav": current_nav,
        }

    def compute_asset_allocation(self, scheme_holdings: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregates equity, debt, and cash allocation percentages across mutual fund scheme holdings.
        """
        total_weight = sum(h.get("weight", 0.0) for h in scheme_holdings) or 1.0
        equity_pct = sum(h.get("weight", 0.0) for h in scheme_holdings if h.get("type", "").lower() == "equity") / total_weight
        debt_pct = sum(h.get("weight", 0.0) for h in scheme_holdings if h.get("type", "").lower() == "debt") / total_weight
        cash_pct = max(0.0, 1.0 - (equity_pct + debt_pct))

        return {
            "equity_percentage": round(equity_pct * 100, 2),
            "debt_percentage": round(debt_pct * 100, 2),
            "cash_percentage": round(cash_pct * 100, 2),
            "total_schemes": len(scheme_holdings),
        }


class MFToolAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter for Indian Mutual Fund Analytics & Execution Engine (mftool).
    Registered in IndianBrokerPluginRegistry under MFTOOL and MFTOOL_MUTUAL_FUND_ENGINE.
    """

    def __init__(self, is_sandbox: bool = True) -> None:
        super().__init__("MFTOOL_MUTUAL_FUND_ENGINE", is_sandbox=is_sandbox)
        self.engine = MFToolEngine()
        self._connected = True

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self) -> dict[str, Any]:
        return {
            "broker": "MFTOOL_MUTUAL_FUND_ENGINE",
            "currency": "INR",
            "balance": 1000000.0,
            "equity": 1000000.0,
            "is_sandbox": self.is_sandbox,
        }

    def get_current_price(self, symbol: str, exchange: str = "MF") -> dict[str, float]:
        return {
            "last": 125.45,
            "bid": 125.40,
            "ask": 125.50,
        }

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        dt_now = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
        if not validate_ist_market_session(dt_now) and not self.is_sandbox:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED_MARKET_CLOSED",
                product=request.product,
                exchange=request.exchange or "MF",
                error="Execution blocked: Outside IST market session hours.",
            )

        rounded_price = round_tick_005(request.price) if request.price > 0 else 125.45

        return SEBIOrderResponse(
            success=True,
            ticket=f"MF_{int(dt_now.timestamp() * 1000)}",
            price=rounded_price,
            status="EXECUTED",
            product=request.product,
            exchange=request.exchange or "MF",
            raw_response={"symbol": request.symbol, "quantity": request.quantity},
        )

    def close_order(
        self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC"
    ) -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=125.45,
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
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "close": 125.45} for _ in range(count)]

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        return True


IndianBrokerPluginRegistry.register("MFTOOL", MFToolAdapter)
IndianBrokerPluginRegistry.register("MFTOOL_MUTUAL_FUND_ENGINE", MFToolAdapter)
