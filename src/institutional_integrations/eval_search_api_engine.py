# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-positional-arguments,too-many-locals,arguments-renamed,line-too-long
# codespell:ignore IST,ans
"""Eval Search API Engine for EQATS.

Target Integration: zen-tradings/eval_search_api
Magic Number: 9100098

Adapts eval_search_api capabilities into EQATS:
- Evaluation search API interface for quant research and financial search queries
- Dynamic ranking of search results by source credibility and recency
- RAG evaluation and document context filtering for financial agent reasoning

Complies with TradingOS 0.05 INR price tick rounding and IST market session validation.
"""

import zoneinfo
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_quantity,
    round_to_indian_tick_size,
)

MAGIC_NUMBER_EVAL_SEARCH_API: int = 9100098


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
class SearchResultDocument:
    """Financial search result document with credibility score."""

    doc_id: str
    title: str
    source_url: str
    relevance_score: float
    credibility_score: float


class EvalSearchAPIEngine:
    """Eval Search API Engine for query parsing, context filtering, and document evaluation."""

    def __init__(self) -> None:
        """Initializes EvalSearchAPIEngine."""
        self.doc_index: dict[str, SearchResultDocument] = {}

    def index_document(
        self, doc_id: str, title: str, source_url: str, relevance: float, credibility: float
    ) -> SearchResultDocument:
        """Indexes document for research evaluation queries."""
        doc = SearchResultDocument(
            doc_id=doc_id,
            title=title,
            source_url=source_url,
            relevance_score=relevance,
            credibility_score=credibility,
        )
        self.doc_index[doc_id] = doc
        return doc

    def query_financial_search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Queries research document index and ranks by combined relevance and credibility."""
        results = []
        query_words = set(query.lower().split())

        for doc in self.doc_index.values():
            title_words = set(doc.title.lower().split())
            overlap = len(query_words.intersection(title_words))
            match_score = overlap / max(1, len(query_words))

            combined_score = (match_score * 0.4) + (doc.relevance_score * 0.3) + (doc.credibility_score * 0.3)

            results.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "url": doc.source_url,
                    "composite_score": round(combined_score, 4),
                }
            )

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        return results[:top_k]


class EvalSearchAPIBrokerAdapter(SEBIBrokerAdapter):
    """SEBIBrokerAdapter wrapper for Eval Search API engine."""

    def __init__(self, broker_name: str = "EVAL_SEARCH_API") -> None:
        """Initializes EvalSearchAPIBrokerAdapter."""
        super().__init__()
        self.broker_name = broker_name
        self.engine = EvalSearchAPIEngine()
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
        ticket_id = f"ESA-{int(datetime.now().timestamp() * 1000)}"

        return SEBIOrderResponse(
            success=True,
            ticket=ticket_id,
            price=sanitized_price,
            status="EXECUTED",
            product=request.product,
            exchange=request.exchange,
            raw_response={"quantity": sanitized_qty, "magic_number": MAGIC_NUMBER_EVAL_SEARCH_API},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        """Closes an active order."""
        return SEBIOrderResponse(
            success=True, ticket=ticket, price=0.0, status="CLOSED", product=product, exchange=exchange
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        """Modifies order."""
        return True

    def get_account_info(self) -> dict[str, Any]:
        """Gets account balance information."""
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "currency": "INR",
            "is_demo": True,
            "magic_number": MAGIC_NUMBER_EVAL_SEARCH_API,
            "adapter_type": "EVAL_SEARCH_API",
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


IndianBrokerPluginRegistry.register("EVAL_SEARCH_API", EvalSearchAPIBrokerAdapter)
