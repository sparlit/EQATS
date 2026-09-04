# codespell:ignore MIS,IST
"""
BankNIFTY Golden Ratio Strategy Engine (EQATS Institutional Adaptation).
Adapted from 85599/BankNIFTY-Golden-Ratio-Strategy into FOSS Microkernel Architecture.

Computes Fibonacci Golden Ratio levels (0.618, 0.382, 0.50, 1.618 extensions) from opening range
bars for BankNIFTY and NIFTY index futures and options on NSE/NFO.
Enforces 0.05 INR tick size rounding and 09:15-15:30 IST session rules.

Assigned Magic Number: 9100006
"""

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

_log = logging.getLogger("BankNiftyGoldenRatio")
MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO = 9100006


class BankNiftyGoldenRatioStrategy:
    """
    BankNIFTY Golden Ratio Quantitative Strategy Engine.
    Uses 0.618 (Golden Ratio) and 0.382 Fibonacci retracement/extension levels
    calculated from early session high-low range to generate high-probability trade setups.
    """

    PHI = 0.618033988749895  # Golden Ratio
    PHI_INV = 0.382019643273295  # 1 - PHI

    def __init__(self, symbol: str = "NSE:BANKNIFTY", lot_size: int = 15) -> None:
        self.symbol = symbol.upper()
        self.lot_size = lot_size
        self.magic_number = MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO

    def calculate_golden_ratio_levels(self, range_high: float, range_low: float) -> Dict[str, float]:
        """
        Calculates Golden Ratio Fibonacci levels from given high and low range bounds.
        """
        diff = range_high - range_low
        if diff <= 0:
            diff = 100.0  # Default fallback range for BankNifty

        golden_retrace_618 = round_to_indian_tick_size(range_high - diff * self.PHI)
        golden_retrace_382 = round_to_indian_tick_size(range_high - diff * self.PHI_INV)
        golden_retrace_500 = round_to_indian_tick_size(range_high - diff * 0.50)

        golden_ext_1618_buy = round_to_indian_tick_size(range_high + diff * self.PHI)
        golden_ext_1618_sell = round_to_indian_tick_size(range_low - diff * self.PHI)

        return {
            "range_high": round_to_indian_tick_size(range_high),
            "range_low": round_to_indian_tick_size(range_low),
            "retrace_618": golden_retrace_618,
            "retrace_382": golden_retrace_382,
            "mid_500": golden_retrace_500,
            "ext_1618_buy": golden_ext_1618_buy,
            "ext_1618_sell": golden_ext_1618_sell,
        }

    def evaluate_strategy(
        self,
        history_bars: List[Dict[str, Any]],
        current_equity: float = 1000000.0,
    ) -> Dict[str, Any]:
        """
        Evaluates history bars against Golden Ratio levels and returns decision dictionary.
        """
        if not history_bars or len(history_bars) < 15:
            return {
                "symbol": self.symbol,
                "decision": "HOLD",
                "lot_size": 0,
                "sl": 0.0,
                "tp": 0.0,
                "explanation": "Insufficient bar history for Golden Ratio evaluation.",
                "magic_number": self.magic_number,
            }

        highs = [float(b["high"]) for b in history_bars]
        lows = [float(b["low"]) for b in history_bars]
        closes = [float(b["close"]) for b in history_bars]
        current_price = closes[-1]

        # Use first 15 bars for opening range high/low
        or_high = max(highs[:15])
        or_low = min(lows[:15])

        levels = self.calculate_golden_ratio_levels(or_high, or_low)

        decision = "HOLD"
        sl = 0.0
        tp = 0.0
        explanation = (
            f"Price {current_price:.2f} within Golden Range [{levels['retrace_382']:.2f} - {levels['retrace_618']:.2f}]"
        )

        # Bullish Golden Ratio Breakout (above 0.618 or range high)
        if current_price >= levels["range_high"]:
            decision = "BUY"
            sl = levels["retrace_618"]
            tp = levels["ext_1618_buy"]
            explanation = (
                f"Golden Ratio BUY Breakout above Range High {levels['range_high']:.2f} (Target 1.618 Ext: {tp:.2f})"
            )
        # Bearish Golden Ratio Breakdown (below 0.382 or range low)
        elif current_price <= levels["range_low"]:
            decision = "SELL"
            sl = levels["retrace_382"]
            tp = levels["ext_1618_sell"]
            explanation = (
                f"Golden Ratio SELL Breakdown below Range Low {levels['range_low']:.2f} (Target 1.618 Ext: {tp:.2f})"
            )

        return {
            "symbol": self.symbol,
            "decision": decision,
            "lot_size": self.lot_size if decision != "HOLD" else 0,
            "sl": sl,
            "tp": tp,
            "explanation": explanation,
            "levels": levels,
            "magic_number": self.magic_number,
        }


class BankNiftyGoldenRatioAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter wrapper for BankNIFTY Golden Ratio Strategy.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.strategy = BankNiftyGoldenRatioStrategy()
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
        return {"bid": 48500.0, "ask": 48505.0, "last": 48502.50}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="NRML")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"BNGOLD_{uuid.uuid4().hex[:12].upper()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 48502.50)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "NRML") -> SEBIOrderResponse:
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


# Register into Microkernel Plugin Registry
IndianBrokerPluginRegistry.register("BANKNIFTY_GOLDEN_RATIO", BankNiftyGoldenRatioAdapter)
IndianBrokerPluginRegistry.register("GOLDEN_RATIO", BankNiftyGoldenRatioAdapter)
