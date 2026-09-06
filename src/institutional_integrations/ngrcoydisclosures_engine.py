"""
Corporate Disclosures Engine Integration Module
===============================================
Adapts corporate disclosure parsing, XML RSS feed parsing, insider dealing classification,
and financial statement disclosure event analysis from `ajakaiye33/ngrcoydisclosures`.

Magic Number: 9100034
"""

import xml.etree.ElementTree as ET
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

MAGIC_NUMBER_NGRCOYDISCLOSURES: int = 9100034


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


class CorporateDisclosuresEngine:
    """
    Parses exchange corporate disclosures (XML/RSS feeds) and classifies news events into
    actionable trading signals (Directors Dealings / Insider Buying, Financial Results).
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_NGRCOYDISCLOSURES

    def parse_xml_disclosures(self, xml_content: str) -> List[Dict[str, str]]:
        """
        Parses XML string representing exchange corporate disclosure feed into structured records.
        """
        records: List[Dict[str, str]] = []
        if not xml_content or not xml_content.strip():
            return records

        try:
            root = ET.fromstring(xml_content)
            # Support entry / item tags
            entries = root.findall(".//entry") or root.findall(".//item")
            if not entries and root.tag in ("entry", "item"):
                entries = [root]

            for entry in entries:
                def get_tag_text(tag_names: List[str]) -> str:
                    for tag in tag_names:
                        elem = entry.find(tag)
                        if elem is not None and elem.text:
                            return elem.text.strip()
                    return ""

                record = {
                    "headline": get_tag_text(["Description", "description", "title", "headline"]),
                    "location": get_tag_text(["Url", "url", "link"]),
                    "news_class": get_tag_text(["Type_of_Submission", "submission_type", "category"]),
                    "company_name": get_tag_text(["CompanyName", "company_name"]),
                    "company_symbol": get_tag_text(["CompanySymbol", "symbol", "company_symbol"]),
                    "date_modified": get_tag_text(["Modified", "modified", "updated"]),
                    "date_created": get_tag_text(["Created", "created", "pubDate"]),
                }
                records.append(record)
        except Exception as err:
            logger.error("Failed to parse disclosures XML: %s", err)

        return records

    def analyze_disclosure_event(self, record: Dict[str, str]) -> Dict[str, Any]:
        """
        Evaluates a corporate disclosure record for trade impact.
        Returns sentiment score (-1.0 to +1.0) and recommended action.
        """
        news_class = record.get("news_class", "").lower()
        headline = record.get("headline", "").lower()
        symbol = record.get("company_symbol", "UNKNOWN").upper()

        score = 0.0
        event_type = "GENERAL"

        if "director" in news_class or "insider" in news_class or "director" in headline:
            event_type = "INSIDER_DEALINGS"
            if any(w in headline for w in ["acquisition", "buy", "bought", "purchase", "accumulate"]):
                score = 0.8
            elif any(w in headline for w in ["disposal", "sale", "sold", "divest"]):
                score = -0.7
            else:
                score = 0.2
        elif "financial" in news_class or "result" in news_class or "statement" in headline:
            event_type = "FINANCIAL_STATEMENTS"
            if any(w in headline for w in ["profit", "surge", "growth", "dividend", "highest"]):
                score = 0.9
            elif any(w in headline for w in ["loss", "decline", "drop", "default", "warning"]):
                score = -0.9
            else:
                score = 0.1

        action = "BUY" if score >= 0.5 else ("SELL" if score <= -0.5 else "HOLD")

        return {
            "symbol": symbol,
            "event_type": event_type,
            "headline": record.get("headline", ""),
            "sentiment_score": score,
            "recommended_action": action,
            "magic_number": self.magic_number,
            "timestamp": datetime.now().isoformat(),
        }


class CorporateDisclosuresBrokerAdapter(SEBIBrokerAdapter):
    """
    Broker Adapter plugin for Corporate Disclosures Engine.
    """

    def __init__(self, broker_name: str = "CorporateDisclosuresBroker") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = CorporateDisclosuresEngine()
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
            ticket=f"NGRCOY-{int(datetime.now().timestamp()*1000)}",
            price=rounded_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
            instrument_token=10002,
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
IndianBrokerPluginRegistry.register("NGRCOY_DISCLOSURES", CorporateDisclosuresBrokerAdapter)
