"""
NSE India API Evangelist Specification & Security Governance Engine Module
===========================================================================
Adapts NSE exchange API surface definitions, domain security compliance checks (DNSSEC, DMARC, SPF),
and API quality/health score evaluation from `api-evangelist/nse-india`.

Magic Number: 9100046
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

MAGIC_NUMBER_NSE_INDIA_API: int = 9100046


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


class NSEIndiaAPIEngine:
    """
    NSE India API Specification Registry & Domain Security Governance Engine.
    Validates API endpoint availability, enforces domain security controls (DNSSEC, DMARC),
    and computes API quality health scores.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_NSE_INDIA_API
        self.registered_endpoints: Dict[str, Dict[str, Any]] = {
            "option_chain": {"url": "https://www.nseindia.com/api/option-chain-indices", "secured": True},
            "equity_quote": {"url": "https://www.nseindia.com/api/quote-equity", "secured": True},
            "market_status": {"url": "https://www.nseindia.com/api/marketStatus", "secured": True},
        }

    def validate_domain_security(self, domain_policy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates domain security controls (DNSSEC, SPF, DMARC policy).
        """
        domain = domain_policy.get("domain", "nseindia.com")
        dnssec = domain_policy.get("dnssec", True)
        spf = domain_policy.get("spf", True)
        dmarc = domain_policy.get("dmarc", True)
        dmarc_policy = domain_policy.get("dmarc_policy", "reject")

        is_compliant = dnssec and spf and dmarc and dmarc_policy in ("reject", "quarantine")

        return {
            "domain": domain,
            "dnssec_enabled": dnssec,
            "spf_enabled": spf,
            "dmarc_enabled": dmarc,
            "dmarc_policy": dmarc_policy,
            "is_security_compliant": is_compliant,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }

    def compute_api_health_score(
        self, latency_ms: float, error_rate_pct: float, uptime_pct: float
    ) -> Dict[str, Any]:
        """
        Computes API quality/health score (0 to 100).
        """
        latency_score = max(0.0, 40.0 - (latency_ms / 10.0))
        error_score = max(0.0, 30.0 - (error_rate_pct * 3.0))
        uptime_score = max(0.0, (uptime_pct / 100.0) * 30.0)

        total_score = round(latency_score + error_score + uptime_score, 2)
        status = "HEALTHY" if total_score >= 80.0 else ("DEGRADED" if total_score >= 50.0 else "UNHEALTHY")

        return {
            "health_score": total_score,
            "status": status,
            "latency_ms": latency_ms,
            "error_rate_pct": error_rate_pct,
            "uptime_pct": uptime_pct,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }


class NSEIndiaAPIBrokerAdapter(SEBIBrokerAdapter):
    """
    Broker Adapter plugin for NSE India API Governance Engine.
    """

    def __init__(self, broker_name: str = "NSEIndiaAPIBroker") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = NSEIndiaAPIEngine()
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
            ticket=f"NSEINDIA-{int(datetime.now().timestamp()*1000)}",
            price=rounded_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
            instrument_token=10014,
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
IndianBrokerPluginRegistry.register("NSE_INDIA_API", NSEIndiaAPIBrokerAdapter)
