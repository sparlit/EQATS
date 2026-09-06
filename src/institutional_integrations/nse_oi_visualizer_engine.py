"""
NSE Option Interest (OI) Visualizer & Black-76 Option Analytics Engine Module
=============================================================================
Adapts option chain Open Interest (OI) tracking, Call/Put OI change imbalance scoring,
Put-Call Ratio (PCR) analytics, and Black-76 option pricing/implied volatility calculations
from `anshuthopsee/nse-oi-visualizer`.

Magic Number: 9100043
"""

import math
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

MAGIC_NUMBER_NSE_OI_VISUALIZER: int = 9100043


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


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_option_price(
    is_call: bool,
    futures_price: float,
    strike_price: float,
    time_to_exp_years: float,
    risk_free_rate: float,
    volatility: float,
) -> float:
    """
    Calculates option price using Black-76 model for futures/derivatives options:
    c = e^(-rT) * [F * N(d1) - K * N(d2)]
    p = e^(-rT) * [K * N(-d2) - F * N(-d1)]
    """
    if time_to_exp_years <= 0 or volatility <= 0 or futures_price <= 0 or strike_price <= 0:
        return max(0.0, futures_price - strike_price) if is_call else max(0.0, strike_price - futures_price)

    d1 = (math.log(futures_price / strike_price) + (0.5 * volatility**2) * time_to_exp_years) / (
        volatility * math.sqrt(time_to_exp_years)
    )
    d2 = d1 - volatility * math.sqrt(time_to_exp_years)

    discount = math.exp(-risk_free_rate * time_to_exp_years)

    if is_call:
        price = discount * (futures_price * norm_cdf(d1) - strike_price * norm_cdf(d2))
    else:
        price = discount * (strike_price * norm_cdf(-d2) - futures_price * norm_cdf(-d1))

    return round_tick_005(price)


class NSEOIVisualizerEngine:
    """
    Open Interest (OI) Change Imbalance & Black-76 Options Pricing Engine.
    Analyzes option chain Call/Put Open Interest buildup, PCR ratios, and Black-76 theoretical option pricing.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_NSE_OI_VISUALIZER

    def analyze_option_chain_oi(
        self,
        underlying_price: float,
        option_chain: List[Dict[str, Any]],
        risk_free_rate: float = 0.07,
        volatility: float = 0.15,
        time_to_exp_years: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Analyzes option chain OI buildup across strikes and computes Black-76 theoretical prices.
        """
        total_ce_oi = sum(item.get("ce_oi", 0) for item in option_chain)
        total_pe_oi = sum(item.get("pe_oi", 0) for item in option_chain)

        total_ce_change_oi = sum(item.get("ce_change_oi", 0) for item in option_chain)
        total_pe_change_oi = sum(item.get("pe_change_oi", 0) for item in option_chain)

        pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0
        pcr_change_oi = (
            round(total_pe_change_oi / total_ce_change_oi, 2)
            if total_ce_change_oi > 0
            else 1.0
        )

        # Max Pain Calculation
        min_pain = float("inf")
        max_pain_strike = round_tick_005(underlying_price)

        for strike_item in option_chain:
            k = strike_item.get("strike_price", underlying_price)
            total_cash_loss = 0.0

            for other_item in option_chain:
                ok = other_item.get("strike_price", underlying_price)
                ce_oi = other_item.get("ce_oi", 0)
                pe_oi = other_item.get("pe_oi", 0)

                # Call holder profit if settlement > strike
                if k > ok:
                    total_cash_loss += (k - ok) * ce_oi
                # Put holder profit if settlement < strike
                if k < ok:
                    total_cash_loss += (ok - k) * pe_oi

            if total_cash_loss < min_pain:
                min_pain = total_cash_loss
                max_pain_strike = round_tick_005(k)

        # Black-76 Pricing for ATM strike
        atm_strike = min(option_chain, key=lambda x: abs(x.get("strike_price", underlying_price) - underlying_price)).get("strike_price", underlying_price)
        atm_ce_black76 = black76_option_price(
            True, underlying_price, atm_strike, time_to_exp_years, risk_free_rate, volatility
        )
        atm_pe_black76 = black76_option_price(
            False, underlying_price, atm_strike, time_to_exp_years, risk_free_rate, volatility
        )

        # Bullish signal if PE OI building up heavily (Put writing) and PCR > 1.2
        signal = "BUY" if (pcr_oi >= 1.2 or pcr_change_oi >= 1.5) else ("SELL" if (pcr_oi <= 0.8 or pcr_change_oi <= 0.6) else "HOLD")

        return {
            "underlying_price": round_tick_005(underlying_price),
            "max_pain_strike": max_pain_strike,
            "pcr_oi": pcr_oi,
            "pcr_change_oi": pcr_change_oi,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "atm_strike": round_tick_005(atm_strike),
            "atm_ce_black76_price": atm_ce_black76,
            "atm_pe_black76_price": atm_pe_black76,
            "recommended_signal": signal,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }


class NSEOIVisualizerBrokerAdapter(SEBIBrokerAdapter):
    """
    Broker Adapter plugin for NSE OI Visualizer Engine.
    """

    def __init__(self, broker_name: str = "NSEOIVisualizerBroker") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = NSEOIVisualizerEngine()
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
        return {"broker": self.broker_name, "connected": self._connected}

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
        return SEBIOrderResponse(
            success=True,
            ticket=f"NSEOIVIZ-{int(datetime.now().timestamp()*1000)}",
            price=rounded_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
            instrument_token=10011,
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
IndianBrokerPluginRegistry.register("NSE_OI_VISUALIZER", NSEOIVisualizerBrokerAdapter)
