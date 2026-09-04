# codespell:ignore MIS,IST
"""
AI Finance Real-Time Stock Analysis Engine (EQATS Institutional Adaptation).
Adapted from abhiwalia15/AI-for-Finance-Stocks-real-time-analysis- into FOSS Microkernel Architecture.

Provides real-time multi-factor stock analysis, technical momentum scoring, news polarity sentiment aggregation,
and composite trend prediction for Indian equities and F&O stocks with 0.05 INR tick size rounding.

Assigned Magic Number: 9100016
"""

import json
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .indian_market_state_machine import global_indian_state_machine, round_to_indian_tick_size
from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    generate_indian_market_history_bars,
    round_to_indian_quantity,
    validate_indian_product_tag,
)

_log = logging.getLogger("AIFinanceStockAnalysisEngine")
MAGIC_NUMBER_AI_FINANCE_ANALYSIS = 9100016


class AIFinanceStockAnalysisEngine:
    """
    Real-Time AI Stock Analysis & Predictive Sentiment Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_AI_FINANCE_ANALYSIS

    def analyze_news_sentiment(self, headlines: List[str]) -> Dict[str, Any]:
        """
        Analyzes headline text polarity to derive news sentiment score (-1.0 to +1.0).
        """
        if not headlines:
            return {"sentiment_score": 0.0, "bias": "NEUTRAL", "sample_count": 0}

        bullish_keywords = [
            "growth",
            "profit",
            "surge",
            "gain",
            "breakout",
            "record",
            "upgrade",
            "buy",
            "expansion",
            "dividend",
        ]
        bearish_keywords = [
            "loss",
            "drop",
            "decline",
            "fall",
            "downgrade",
            "sell",
            "debt",
            "crisis",
            "penalty",
            "lawsuit",
        ]

        score_total = 0.0
        for headline in headlines:
            text = headline.lower()
            b_count = sum(1 for kw in bullish_keywords if kw in text)
            r_count = sum(1 for kw in bearish_keywords if kw in text)
            if b_count + r_count > 0:
                score_total += (b_count - r_count) / float(b_count + r_count)

        avg_score = score_total / float(len(headlines))
        avg_score = round(max(-1.0, min(1.0, avg_score)), 2)

        bias = "BULLISH" if avg_score >= 0.20 else "BEARISH" if avg_score <= -0.20 else "NEUTRAL"
        return {"sentiment_score": avg_score, "bias": bias, "sample_count": len(headlines)}

    def analyze_realtime_stock(
        self,
        symbol: str,
        history_bars: List[Dict[str, Any]],
        news_headlines: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Runs comprehensive real-time multi-factor analysis on a stock.
        """
        if not history_bars or len(history_bars) < 20:
            return {
                "symbol": symbol,
                "composite_score": 50.0,
                "action": "HOLD",
                "confidence": 0.50,
                "magic_number": self.magic_number,
            }

        closes = [float(b["close"]) for b in history_bars]
        highs = [float(b["high"]) for b in history_bars]
        lows = [float(b["low"]) for b in history_bars]
        current_price = closes[-1]

        # Technical Score (0.0 to 100.0)
        ema20 = sum(closes[-20:]) / 20.0
        trend_score = 65.0 if current_price > ema20 else 35.0

        # Sentiment Score
        news_res = self.analyze_news_sentiment(news_headlines or [])
        sent_component = (news_res["sentiment_score"] + 1.0) * 50.0  # Convert [-1, 1] -> [0, 100]

        # Composite Score (70% Technical, 30% Sentiment)
        composite_score = round(0.70 * trend_score + 0.30 * sent_component, 2)

        action = "BUY" if composite_score >= 65.0 else "SELL" if composite_score <= 35.0 else "HOLD"
        confidence = round(abs(composite_score - 50.0) / 50.0 + 0.50, 2)

        sl = 0.0
        tp = 0.0
        if action == "BUY":
            sl = round_to_indian_tick_size(current_price * 0.985)
            tp = round_to_indian_tick_size(current_price * 1.03)
        elif action == "SELL":
            sl = round_to_indian_tick_size(current_price * 1.015)
            tp = round_to_indian_tick_size(current_price * 0.97)

        return {
            "symbol": symbol,
            "composite_score": composite_score,
            "action": action,
            "confidence": min(0.95, confidence),
            "entry_price": round_to_indian_tick_size(current_price),
            "sl": sl,
            "tp": tp,
            "sentiment_details": news_res,
            "magic_number": self.magic_number,
        }


class AIFinanceStockAnalysisAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter for AI Finance Real-Time Stock Analysis Engine.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.engine = AIFinanceStockAnalysisEngine()
        self.simulated_orders: Dict[str, Dict[str, Any]] = {}

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {"balance": 1000000.0, "equity": 1000000.0, "currency": "INR", "is_demo": self.is_sandbox}

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> List[Dict[str, Any]]:
        return generate_indian_market_history_bars(symbol, exchange, count, interval)

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 2850.0, "ask": 2850.15, "last": 2850.05}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="CNC")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"AIFIN_{time.time_ns()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 2850.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_AI_FINANCE_ANALYSIS,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_AI_FINANCE_ANALYSIS},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        if ticket in self.simulated_orders:
            self.simulated_orders.pop(ticket)
        return SEBIOrderResponse(
            success=True, ticket=ticket, price=0.0, status="CLOSED", product=product, exchange=exchange
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        if ticket in self.simulated_orders:
            if price > 0:
                self.simulated_orders[ticket]["price"] = round_to_indian_tick_size(price)
            return True
        return True

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return list(self.simulated_orders.values())


# Auto-register into Microkernel Plugin Registry
IndianBrokerPluginRegistry.register("AI_FINANCE_STOCK_ANALYSIS", AIFinanceStockAnalysisAdapter)
IndianBrokerPluginRegistry.register("AI_FINANCE", AIFinanceStockAnalysisAdapter)
