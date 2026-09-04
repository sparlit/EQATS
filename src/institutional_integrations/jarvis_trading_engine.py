# codespell:ignore MIS,IST
"""
Jarvis Composite Quantitative Stock Screener & Trading Engine (EQATS Institutional Adaptation).
Adapted from agrawalarnav129-ui/jarvis-trading into FOSS Microkernel Architecture.

Features a 5-dimensional weighted composite scoring model:
  - Price Action & Trend Alignment (25%)
  - Trend Strength / ADX (25%)
  - Relative Strength vs Benchmark (20%)
  - Momentum Indicators (15%)
  - Volume Quality & Accumulation (15%)
Along with market regime-aware position sizing, 0.05 INR tick size rounding, and SEBIBrokerAdapter integration.

Assigned Magic Number: 9100032
"""

import logging
import math
import uuid
from typing import Any, Dict, List, Optional

from .indian_market_state_machine import round_to_indian_tick_size
from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    generate_indian_market_history_bars,
    validate_indian_product_tag,
)

_log = logging.getLogger("JarvisTradingEngine")
MAGIC_NUMBER_JARVIS_TRADING = 9100032


class JarvisTradingStrategy:
    """
    5-Dimensional Composite Quantitative Stock Screener & Market Regime Trading Engine.
    Evaluates Price Action (25%), Trend Strength (25%), Relative Strength (20%),
    Momentum (15%), and Volume Quality (15%).
    """

    def __init__(
        self,
        symbol: str = "NIFTY",
        min_composite_score: float = 65.0,
        regime: str = "BULL",
    ) -> None:
        self.symbol = symbol.upper()
        self.min_composite_score = min_composite_score
        self.regime = regime.upper()
        self.magic_number = MAGIC_NUMBER_JARVIS_TRADING

    def calculate_composite_score(
        self,
        price_trend_score: float = 80.0,
        trend_strength_adx_score: float = 75.0,
        relative_strength_score: float = 70.0,
        momentum_score: float = 65.0,
        volume_quality_score: float = 60.0,
    ) -> float:
        """
        Calculates the 5-factor weighted score (0 - 100).
        Weights:
          Price Trend: 25%
          Trend Strength: 25%
          Relative Strength: 20%
          Momentum: 15%
          Volume Quality: 15%
        """
        weighted_score = (
            (price_trend_score * 0.25)
            + (trend_strength_adx_score * 0.25)
            + (relative_strength_score * 0.20)
            + (momentum_score * 0.15)
            + (volume_quality_score * 0.15)
        )
        return round(weighted_score, 2)

    def evaluate_strategy(
        self,
        history_bars: List[Dict[str, Any]],
        benchmark_close: float = 22000.0,
        benchmark_prev_close: float = 21900.0,
    ) -> Dict[str, Any]:
        if not history_bars or len(history_bars) < 2:
            return {
                "symbol": self.symbol,
                "decision": "HOLD",
                "quantity": 0,
                "score": 0.0,
                "explanation": "Insufficient history bars for Jarvis composite evaluation.",
                "magic_number": self.magic_number,
            }

        last_bar = history_bars[-1]
        prev_bar = history_bars[-2]
        close = float(last_bar["close"])
        prev_close = float(prev_bar["close"])

        stock_return = (close - prev_close) / prev_close if prev_close > 0 else 0.0
        benchmark_return = (
            (benchmark_close - benchmark_prev_close) / benchmark_prev_close if benchmark_prev_close > 0 else 0.0
        )

        # Factor 1: Price Action Trend Score
        price_trend = 80.0 if close > prev_close else 30.0

        # Factor 2: Trend Strength Score (Simulated ADX proxy based on range)
        bar_range = float(last_bar["high"]) - float(last_bar["low"])
        trend_strength = min(100.0, max(20.0, (bar_range / close) * 2000.0))

        # Factor 3: Relative Strength vs Benchmark
        rel_strength = 75.0 if stock_return >= benchmark_return else 35.0

        # Factor 4: Momentum Score
        momentum = 70.0 if stock_return > 0 else 30.0

        # Factor 5: Volume Quality Score
        vol = float(last_bar.get("volume", 1000.0))
        prev_vol = float(prev_bar.get("volume", 1000.0))
        vol_quality = 85.0 if vol > prev_vol and stock_return > 0 else 40.0

        composite_score = self.calculate_composite_score(
            price_trend, trend_strength, rel_strength, momentum, vol_quality
        )

        # Regime Sizing Factor
        sizing_multiplier = 1.0
        if self.regime == "BEAR":
            sizing_multiplier = 0.5
        elif self.regime == "RANGE":
            sizing_multiplier = 0.75

        decision = "HOLD"
        quantity = 0
        sl = 0.0
        tp = 0.0

        if composite_score >= self.min_composite_score:
            decision = "BUY"
            quantity = int(20 * sizing_multiplier)
            sl = round_to_indian_tick_size(close * 0.98)
            tp = round_to_indian_tick_size(close * 1.04)
        elif composite_score <= 35.0:
            decision = "SELL"
            quantity = int(20 * sizing_multiplier)
            sl = round_to_indian_tick_size(close * 1.02)
            tp = round_to_indian_tick_size(close * 0.96)

        return {
            "symbol": self.symbol,
            "decision": decision,
            "score": composite_score,
            "quantity": quantity,
            "sl": sl,
            "tp": tp,
            "regime": self.regime,
            "explanation": f"Jarvis Composite Score: {composite_score:.2f}/100 (Threshold: {self.min_composite_score}). Regime: {self.regime}.",
            "magic_number": self.magic_number,
        }


class JarvisTradingAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter wrapper for Jarvis Composite Engine.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.strategy = JarvisTradingStrategy()
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
        return {"bid": 22000.0, "ask": 22001.0, "last": 22000.50}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="MIS")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"JARVIS_{uuid.uuid4().hex[:12].upper()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 22000.50)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_JARVIS_TRADING,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_JARVIS_TRADING},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "MIS") -> SEBIOrderResponse:
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


IndianBrokerPluginRegistry.register("JARVIS_TRADING", JarvisTradingAdapter)
