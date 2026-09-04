# codespell:ignore MIS,IST
"""
Indian Share Market Analytics & Sector Momentum Engine (EQATS Institutional Adaptation).
Adapted from abuhurairalakdawala/indian-share-market into FOSS Microkernel Architecture.

Provides Indian stock market fundamental valuation scoring (P/E, P/B, ROE, Debt/Equity),
NSE sector momentum matrix analysis, and portfolio CAGR / risk analytics
with 0.05 INR tick size rounding and 09:15-15:30 IST session rules.

Assigned Magic Number: 9100009
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

_log = logging.getLogger("IndianShareMarketEngine")
MAGIC_NUMBER_INDIAN_SHARE_MARKET = 9100009


class IndianShareMarketEngine:
    """
    Indian Share Market Fundamental Valuation & Sector Momentum Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_INDIAN_SHARE_MARKET

    def evaluate_fundamental_score(
        self, pe_ratio: float, pb_ratio: float, roe_pct: float, debt_to_equity: float, div_yield_pct: float
    ) -> Dict[str, Any]:
        """
        Calculates composite fundamental valuation score (0.0 to 100.0) for an Indian equity stock.
        """
        score = 50.0

        # P/E Score (Ideal: 10 - 25)
        if 0 < pe_ratio <= 15:
            score += 15.0
        elif 15 < pe_ratio <= 25:
            score += 10.0
        elif pe_ratio > 40:
            score -= 10.0

        # P/B Score (Ideal < 3.0)
        if 0 < pb_ratio <= 2.0:
            score += 10.0
        elif pb_ratio > 5.0:
            score -= 5.0

        # ROE Score (Ideal > 15%)
        if roe_pct >= 20.0:
            score += 15.0
        elif roe_pct >= 15.0:
            score += 10.0
        elif roe_pct < 8.0:
            score -= 10.0

        # Debt to Equity (Ideal < 0.5)
        if debt_to_equity <= 0.3:
            score += 10.0
        elif debt_to_equity <= 0.8:
            score += 5.0
        elif debt_to_equity > 1.5:
            score -= 15.0

        # Dividend Yield
        if div_yield_pct >= 2.0:
            score += 5.0

        final_score = round(max(0.0, min(100.0, score)), 2)
        rating = (
            "STRONG_BUY"
            if final_score >= 75.0
            else "BUY"
            if final_score >= 60.0
            else "HOLD"
            if final_score >= 40.0
            else "SELL"
        )

        return {
            "fundamental_score": final_score,
            "rating": rating,
            "pe_ratio": round(pe_ratio, 2),
            "pb_ratio": round(pb_ratio, 2),
            "roe_pct": round(roe_pct, 2),
            "debt_to_equity": round(debt_to_equity, 2),
            "div_yield_pct": round(div_yield_pct, 2),
            "magic_number": self.magic_number,
        }

    def evaluate_sector_momentum(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns sector momentum matrix across major NSE sectors.
        """
        sectors = {
            "NIFTY_BANK": {"change_pct": 1.25, "momentum": "BULLISH", "top_pick": "HDFCBANK"},
            "NIFTY_IT": {"change_pct": 0.85, "momentum": "BULLISH", "top_pick": "INFY"},
            "NIFTY_AUTO": {"change_pct": -0.45, "momentum": "BEARISH", "top_pick": "TATAMOTORS"},
            "NIFTY_PHARMA": {"change_pct": 0.15, "momentum": "NEUTRAL", "top_pick": "SUNPHARMA"},
            "NIFTY_METAL": {"change_pct": 2.10, "momentum": "STRONG_BULLISH", "top_pick": "TATASTEEL"},
            "NIFTY_FMCG": {"change_pct": -0.10, "momentum": "NEUTRAL", "top_pick": "ITC"},
        }
        return sectors

    def calculate_portfolio_cagr_sharpe(
        self, initial_capital: float, current_value: float, duration_years: float, returns_list: List[float]
    ) -> Dict[str, float]:
        """
        Calculates portfolio Compound Annual Growth Rate (CAGR) and Sharpe Ratio.
        """
        if initial_capital <= 0 or current_value <= 0 or duration_years <= 0:
            return {"cagr_pct": 0.0, "sharpe_ratio": 0.0}

        cagr = ((current_value / initial_capital) ** (1.0 / duration_years) - 1.0) * 100.0

        if not returns_list or len(returns_list) < 2:
            return {"cagr_pct": round(cagr, 2), "sharpe_ratio": 1.0}

        mean_ret = sum(returns_list) / float(len(returns_list))
        var_ret = sum((r - mean_ret) ** 2 for r in returns_list) / float(len(returns_list))
        std_ret = math.sqrt(var_ret) if var_ret > 0 else 0.001

        sharpe = (mean_ret - 0.0002) / std_ret * math.sqrt(252)

        return {
            "cagr_pct": round(cagr, 2),
            "sharpe_ratio": round(sharpe, 2),
            "current_value": round_to_indian_tick_size(current_value),
        }


class IndianShareMarketAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter for Indian Share Market Analytics.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.engine = IndianShareMarketEngine()
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
        return {"bid": 830.0, "ask": 830.15, "last": 830.05}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="CNC")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"INMKT_{time.time_ns()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 830.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_INDIAN_SHARE_MARKET,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_INDIAN_SHARE_MARKET},
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
IndianBrokerPluginRegistry.register("INDIAN_SHARE_MARKET", IndianShareMarketAdapter)
IndianBrokerPluginRegistry.register("SHARE_MARKET", IndianShareMarketAdapter)
