"""
EOD2 Relative Strength & Market Breadth Engine (BennyThadikaran/eod2 Adaptation)
=============================================================================

Target Integration: BennyThadikaran/eod2
Magic Number: 9100073

Provides Dorsey Relative Strength, Mansfield Relative Strength, market breadth metrics
(% above 50/200 MA, 52-week High/Low tracking), 0.05 INR price tick rounding,
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

MAGIC_NUMBER_EOD2: int = 9100073


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


class EOD2Engine:
    """
    Dorsey/Mansfield Relative Strength & Market Breadth Engine.
    """

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self.magic_number = MAGIC_NUMBER_EOD2

    def compute_dorsey_rs(self, stock_close: float, index_close: float) -> float:
        """
        Calculates Dorsey Relative Strength = (Stock Close / Index Close) * 100.
        """
        if index_close <= 0:
            return 0.0
        return round((stock_close / index_close) * 100.0, 2)

    def compute_mansfield_rs(self, stock_closes: List[float], index_closes: List[float]) -> Dict[str, Any]:
        """
        Calculates Mansfield Relative Strength over rolling period.
        """
        if not stock_closes or not index_closes or len(stock_closes) < self.period or len(stock_closes) != len(index_closes):
            return {"mansfield_rs": 0.0, "signal": "NEUTRAL", "magic_number": self.magic_number}

        rs_series = [self.compute_dorsey_rs(stock_closes[i], index_closes[i]) for i in range(len(stock_closes))]
        recent_rs = rs_series[-self.period :]
        sma_rs = sum(recent_rs) / len(recent_rs) if len(recent_rs) > 0 else 1.0

        current_rs = rs_series[-1]
        mansfield_rs = round(((current_rs / sma_rs) - 1.0) * 100.0, 2) if sma_rs > 0 else 0.0

        if mansfield_rs >= 1.0:
            signal = "MANSFIELD_BULLISH"
        elif mansfield_rs <= -1.0:
            signal = "MANSFIELD_BEARISH"
        else:
            signal = "NEUTRAL"

        return {
            "current_dorsey_rs": current_rs,
            "sma_rs": round(sma_rs, 2),
            "mansfield_rs": mansfield_rs,
            "signal": signal,
            "magic_number": self.magic_number,
        }

    def evaluate_market_breadth(self, stock_snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates market breadth metrics: % above MA50, % above MA200, 52WH count, 52WL count.
        """
        if not stock_snapshots:
            return {
                "total_stocks": 0,
                "pct_above_ma50": 0.0,
                "pct_above_ma200": 0.0,
                "new_52w_highs": 0,
                "new_52w_lows": 0,
                "magic_number": self.magic_number,
            }

        above_ma50 = 0
        above_ma200 = 0
        highs_52w = 0
        lows_52w = 0

        for stock in stock_snapshots:
            close = stock.get("close", 0.0)
            ma50 = stock.get("ma50", 0.0)
            ma200 = stock.get("ma200", 0.0)
            high_52w = stock.get("high_52w", 0.0)
            low_52w = stock.get("low_52w", 0.0)

            if close > ma50 > 0:
                above_ma50 += 1
            if close > ma200 > 0:
                above_ma200 += 1
            if close >= high_52w > 0:
                highs_52w += 1
            if close <= low_52w and low_52w > 0:
                lows_52w += 1

        total = len(stock_snapshots)
        return {
            "total_stocks": total,
            "pct_above_ma50": round((above_ma50 / total) * 100.0, 2),
            "pct_above_ma200": round((above_ma200 / total) * 100.0, 2),
            "new_52w_highs": highs_52w,
            "new_52w_lows": lows_52w,
            "magic_number": self.magic_number,
        }


class EOD2BrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for EOD2 Engine.
    """

    def __init__(self, broker_name: str = "EOD2") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = EOD2Engine()

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
        ticket_id = f"EOD-{int(datetime.now().timestamp() * 1000)}"

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
IndianBrokerPluginRegistry.register("EOD2", EOD2BrokerAdapter)
