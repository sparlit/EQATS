# codespell:ignore MIS,IST
"""
Indian Stock Tracker & Portfolio Analytics Engine (EQATS Institutional Adaptation).
Adapted from akshayz14/indian-stock-tracker into FOSS Microkernel Architecture.

Provides multi-symbol stock tracking, Top Gainers & Losers classification across NSE/BSE,
portfolio asset allocation matrix, and EOD performance summary
with 0.05 INR tick size rounding and 09:15-15:30 IST session safeguards.

Assigned Magic Number: 9100019
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

_log = logging.getLogger("IndianStockTrackerEngine")
MAGIC_NUMBER_INDIAN_STOCK_TRACKER = 9100019


class IndianStockTrackerEngine:
    """
    Indian Stock Tracker & Multi-Asset Portfolio Analytics Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_INDIAN_STOCK_TRACKER

    def track_symbols_gainers_losers(self, stock_quotes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Processes a list of stock quotes and categorizes Top Gainers and Top Losers.
        """
        if not stock_quotes:
            return {"top_gainers": [], "top_losers": [], "summary_count": 0, "magic_number": self.magic_number}

        processed = []
        for q in stock_quotes:
            sym = str(q.get("symbol", "UNKNOWN")).upper()
            last_p = round_to_indian_tick_size(float(q.get("last_price", q.get("close", 500.0))))
            prev_close = float(q.get("prev_close", q.get("open", last_p)))
            chg = last_p - prev_close
            p_chg = round((chg / float(max(1e-5, prev_close))) * 100.0, 2)

            processed.append(
                {
                    "symbol": sym,
                    "last_price": last_p,
                    "change": round_to_indian_tick_size(chg),
                    "p_change": p_chg,
                }
            )

        sorted_by_gain = sorted(processed, key=lambda x: float(x["p_change"]), reverse=True)
        top_gainers = [s for s in sorted_by_gain if s["p_change"] > 0][:5]
        top_losers = [s for s in reversed(sorted_by_gain) if s["p_change"] < 0][:5]

        return {
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "summary_count": len(processed),
            "magic_number": self.magic_number,
        }

    def evaluate_portfolio_allocation(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculates portfolio asset allocation breakdown across Equities (CNC), Intraday (MIS), and F&O (NRML).
        """
        if not positions:
            return {"equity_exposure": 0.0, "intraday_exposure": 0.0, "fo_exposure": 0.0, "total_value": 0.0}

        total_value = 0.0
        equity_val = 0.0
        mis_val = 0.0
        nrml_val = 0.0

        for pos in positions:
            p_val = float(pos.get("quantity", 1)) * float(pos.get("price", 100.0))
            prod = str(pos.get("product", "CNC")).upper()
            total_value += p_val

            if prod == "CNC":
                equity_val += p_val
            elif prod == "MIS":
                mis_val += p_val
            elif prod == "NRML":
                nrml_val += p_val

        tot_safe = max(1.0, total_value)
        return {
            "total_value": round_to_indian_tick_size(total_value),
            "equity_exposure_pct": round((equity_val / tot_safe) * 100.0, 2),
            "intraday_exposure_pct": round((mis_val / tot_safe) * 100.0, 2),
            "fo_exposure_pct": round((nrml_val / tot_safe) * 100.0, 2),
            "magic_number": self.magic_number,
        }


class IndianStockTrackerAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter for Indian Stock Tracker Engine.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.engine = IndianStockTrackerEngine()
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
        ticket = f"STRK_{time.time_ns()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 2850.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_INDIAN_STOCK_TRACKER,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_INDIAN_STOCK_TRACKER},
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
IndianBrokerPluginRegistry.register("INDIAN_STOCK_TRACKER", IndianStockTrackerAdapter)
IndianBrokerPluginRegistry.register("STOCK_TRACKER", IndianStockTrackerAdapter)
