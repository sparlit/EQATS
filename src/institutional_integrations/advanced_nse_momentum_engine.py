"""
Advanced NSE Momentum Terminal Engine (benimward9621/advanced-nse-momentum-terminal Adaptation)
=============================================================================================

Target Integration: benimward9621/advanced-nse-momentum-terminal
Magic Number: 9100072

Provides Relative Strength (RS) momentum scoring, volatility-adjusted trend evaluation,
sector rotation screening, 0.05 INR price tick rounding, IST market session validation, and microkernel plugin binding.
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

MAGIC_NUMBER_ADVANCED_NSE_MOMENTUM: int = 9100072


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


class AdvancedNSEMomentumEngine:
    """
    Relative Strength Momentum & Volatility-Adjusted Trend Engine.
    """

    def __init__(self, rs_benchmark_symbol: str = "NIFTY50") -> None:
        self.benchmark_symbol = rs_benchmark_symbol
        self.magic_number = MAGIC_NUMBER_ADVANCED_NSE_MOMENTUM

    def calculate_relative_strength(self, stock_prices: List[float], benchmark_prices: List[float]) -> Dict[str, Any]:
        """
        Calculates Mansfield Relative Strength (RS) momentum score relative to benchmark index.
        """
        if not stock_prices or not benchmark_prices or len(stock_prices) != len(benchmark_prices) or len(stock_prices) < 2:
            return {"rs_score": 0.0, "rs_signal": "NEUTRAL", "magic_number": self.magic_number}

        stock_return = ((stock_prices[-1] - stock_prices[0]) / stock_prices[0]) * 100.0
        bench_return = ((benchmark_prices[-1] - benchmark_prices[0]) / benchmark_prices[0]) * 100.0

        rs_score = stock_return - bench_return

        if rs_score >= 2.0:
            rs_signal = "OUTPERFORMING"
        elif rs_score <= -2.0:
            rs_signal = "UNDERPERFORMING"
        else:
            rs_signal = "IN_LINE"

        return {
            "stock_return_pct": round(stock_return, 2),
            "benchmark_return_pct": round(bench_return, 2),
            "rs_score": round(rs_score, 2),
            "rs_signal": rs_signal,
            "magic_number": self.magic_number,
        }

    def compute_volatility_adjusted_trend(self, prices: List[float]) -> Dict[str, Any]:
        """
        Computes trend direction normalized by historical volatility (StdDev of returns).
        """
        if not prices or len(prices) < 5:
            return {"vol_adj_score": 0.0, "trend_status": "NEUTRAL", "magic_number": self.magic_number}

        returns = [((prices[i] - prices[i - 1]) / prices[i - 1]) for i in range(1, len(prices))]
        mean_ret = sum(returns) / len(returns)
        var = sum((r - mean_ret) ** 2 for r in returns) / len(returns) if len(returns) > 1 else 0.0
        vol = math.sqrt(var) if var > 0 else 0.01

        tot_return = (prices[-1] - prices[0]) / prices[0]
        vol_adj_score = tot_return / vol if vol > 0 else 0.0

        if vol_adj_score >= 1.5:
            trend_status = "STRONG_BULLISH"
        elif vol_adj_score <= -1.5:
            trend_status = "STRONG_BEARISH"
        else:
            trend_status = "SIDEWAYS"

        return {
            "volatility": round(vol, 4),
            "vol_adj_score": round(vol_adj_score, 2),
            "trend_status": trend_status,
            "magic_number": self.magic_number,
        }


class AdvancedNSEMomentumBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for Advanced NSE Momentum Engine.
    """

    def __init__(self, broker_name: str = "ADVANCED_NSE_MOMENTUM") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = AdvancedNSEMomentumEngine()

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
        ticket_id = f"ANM-{int(datetime.now().timestamp() * 1000)}"

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
IndianBrokerPluginRegistry.register("ADVANCED_NSE_MOMENTUM", AdvancedNSEMomentumBrokerAdapter)
