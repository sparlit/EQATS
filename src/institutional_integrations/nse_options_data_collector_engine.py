"""
NSE Options Data Collector Engine (BarathGB007/nse-options-data-collector Adaptation)
===================================================================================

Target Integration: BarathGB007/nse-options-data-collector
Magic Number: 9100068

Provides Open Interest (OI) snapshot processing, PCR calculation, premarket gap analysis,
premarket gap-down ITM put hedge triggers, 0.05 INR price tick rounding, IST market session validation,
and microkernel plugin binding.
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

MAGIC_NUMBER_NSE_OPTIONS_DATA_COLLECTOR: int = 9100068


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


class NSEOptionsDataCollectorEngine:
    """
    NSE Options Data Collector, Premarket Gap Analysis & Gap-Down Protection Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_NSE_OPTIONS_DATA_COLLECTOR

    def process_oi_snapshot(self, option_chain_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Parses option chain records to aggregate Total Call/Put OI and Put-Call Ratio (PCR).
        """
        total_call_oi = 0
        total_put_oi = 0

        for rec in option_chain_records:
            total_call_oi += rec.get("call_oi", 0)
            total_put_oi += rec.get("put_oi", 0)

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

        if pcr >= 1.20:
            bias = "BULLISH_PCR"
        elif pcr <= 0.80:
            bias = "BEARISH_PCR"
        else:
            bias = "NEUTRAL"

        return {
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "pcr": pcr,
            "bias": bias,
            "magic_number": self.magic_number,
        }

    def analyze_premarket_gap(self, prev_close: float, iep_price: float) -> Dict[str, Any]:
        """
        Analyzes premarket Indicative Equilibrium Price (IEP) gap relative to previous close.
        """
        prev_close = round_tick_005(prev_close)
        iep_price = round_tick_005(iep_price)

        gap_amt = iep_price - prev_close
        gap_pct = ((gap_amt) / prev_close) * 100.0 if prev_close > 0 else 0.0

        if gap_pct >= 0.50:
            gap_type = "GAP_UP"
        elif gap_pct <= -0.50:
            gap_type = "GAP_DOWN"
        else:
            gap_type = "FLAT_OPEN"

        return {
            "prev_close": prev_close,
            "iep_price": iep_price,
            "gap_amount": round(gap_amt, 2),
            "gap_percent": round(gap_pct, 2),
            "gap_type": gap_type,
            "magic_number": self.magic_number,
        }

    def evaluate_premarket_gap_hedge_trigger(
        self, prev_close: float, iep_price: float, gap_down_threshold_pct: float = 3.0
    ) -> Dict[str, Any]:
        """
        Evaluates premarket Indicative Equilibrium Price (IEP).
        If premarket gap down <= -gap_down_threshold_pct (default -3.0%), triggers automated ITM Put Hedge order.
        """
        analysis = self.analyze_premarket_gap(prev_close, iep_price)
        gap_pct = analysis["gap_percent"]

        hedge_triggered = gap_pct <= -gap_down_threshold_pct
        action = "PLACE_PUT_HEDGE" if hedge_triggered else "NO_HEDGE"

        return {
            "prev_close": analysis["prev_close"],
            "iep_price": analysis["iep_price"],
            "gap_percent": gap_pct,
            "gap_down_threshold_pct": gap_down_threshold_pct,
            "hedge_triggered": hedge_triggered,
            "recommended_action": action,
            "magic_number": self.magic_number,
        }


class NSEOptionsDataCollectorBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for NSE Options Data Collector Engine.
    """

    def __init__(self, broker_name: str = "NSE_OPTIONS_DATA_COLLECTOR") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = NSEOptionsDataCollectorEngine()

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
        ticket_id = f"ODC-{int(datetime.now().timestamp() * 1000)}"

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


IndianBrokerPluginRegistry.register("NSE_OPTIONS_DATA_COLLECTOR", NSEOptionsDataCollectorBrokerAdapter)
