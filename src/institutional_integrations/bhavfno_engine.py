"""
BhavFnO Analytics & Options Expiry Engine (beinghorizontal/BhavFnO Adaptation)
==========================================================================

Target Integration: beinghorizontal/BhavFnO
Magic Number: 9100071

Provides monthly options expiry date calculation with Thursday and exchange holiday adjustment,
F&O Bhavcopy Open Interest (OI) & Implied Volatility (IV) analytics, 0.05 INR price tick rounding,
IST market session validation, and microkernel plugin binding.
"""

import calendar
import math
import zoneinfo
from typing import Dict, Any, List, Optional
from datetime import datetime, date

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)

MAGIC_NUMBER_BHAVFNO: int = 9100071


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


class BhavFnOEngine:
    """
    BhavFnO Expiry Calculation & Options Microstructure Engine.
    """

    def __init__(self, holidays: Optional[List[str]] = None) -> None:
        self.holidays = holidays or ["26-01-2025", "15-08-2025", "02-10-2025", "25-12-2025"]
        self.magic_number = MAGIC_NUMBER_BHAVFNO

    def calculate_monthly_expiries(self, year: int) -> List[str]:
        """
        Calculates the monthly expiry date (last Thursday or preceding Wednesday if holiday) for each month.
        """
        expiries = ["EMPTY"]
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            day_month = calendar.weekday(year, month, last_day)  # 0: Mon, 3: Thu
            week = [3, 4, 5, 6, 0, 1, 2]
            days_back = 0
            for w in week:
                if w == day_month:
                    break
                days_back += 1

            date_thu = last_day - days_back
            expiry_str = f"{str(date_thu).zfill(2)}-{str(month).zfill(2)}-{year}"

            if expiry_str in self.holidays:
                expiry_str = f"{str(date_thu - 1).zfill(2)}-{str(month).zfill(2)}-{year}"

            expiries.append(expiry_str)

        return expiries

    def compute_bhav_iv_pcr(self, ce_records: List[Dict[str, Any]], pe_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates CE/PE open interest and computes weighted IV and PCR metrics.
        """
        total_ce_oi = sum(r.get("oi", 0) for r in ce_records)
        total_pe_oi = sum(r.get("oi", 0) for r in pe_records)

        ce_iv_avg = sum(r.get("iv", 0.0) for r in ce_records) / len(ce_records) if ce_records else 0.0
        pe_iv_avg = sum(r.get("iv", 0.0) for r in pe_records) / len(pe_records) if pe_records else 0.0

        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0

        if pcr >= 1.20:
            bias = "BULLISH_PCR"
        elif pcr <= 0.80:
            bias = "BEARISH_PCR"
        else:
            bias = "NEUTRAL"

        return {
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "pcr": pcr,
            "ce_iv_avg": round(ce_iv_avg, 2),
            "pe_iv_avg": round(pe_iv_avg, 2),
            "bias": bias,
            "magic_number": self.magic_number,
        }


class BhavFnOBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for BhavFnO Engine.
    """

    def __init__(self, broker_name: str = "BHAVFNO") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = BhavFnOEngine()

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
        ticket_id = f"FNO-{int(datetime.now().timestamp() * 1000)}"

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
IndianBrokerPluginRegistry.register("BHAVFNO", BhavFnOBrokerAdapter)
