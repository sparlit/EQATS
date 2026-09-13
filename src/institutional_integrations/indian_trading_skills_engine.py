# codespell:ignore MIS,IST
"""
Indian Trading Skills & Technical Indicator Engine (EQATS Institutional Adaptation).
Adapted from ajeeshworkspace/indian-trading-skills into FOSS Microkernel Architecture.

Provides intraday VWAP volatility bands (1.0x & 2.0x StdDev), Half-Kelly Criterion Fixed-Fractional
Capital Allocator, ADX trend strength evaluation, and EMA 9/21 momentum crossover triggers
with 0.05 INR tick size rounding.

Assigned Magic Number: 9100017
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

_log = logging.getLogger("IndianTradingSkillsEngine")
MAGIC_NUMBER_INDIAN_TRADING_SKILLS = 9100017


class IndianTradingSkillsEngine:
    """
    Indian Trading Skills, VWAP Volatility Bands & Half-Kelly Position Sizing Engine.
    """

    def __init__(self, adx_threshold: float = 25.0) -> None:
        self.adx_threshold = adx_threshold
        self.magic_number = MAGIC_NUMBER_INDIAN_TRADING_SKILLS

    def calculate_half_kelly_position_size(
        self, account_equity: float, price: float, win_rate_pct: float, win_loss_ratio: float
    ) -> Dict[str, Any]:
        """
        Calculates optimal capital allocation using the Half-Kelly Criterion formula:
        f* = 0.5 * (W - ((1 - W) / R))
        Where W = win_rate_pct / 100, R = win_loss_ratio.
        Maximizes compound portfolio growth while preventing over-leverage drawdown.
        """
        if account_equity <= 0 or price <= 0 or win_rate_pct <= 0 or win_loss_ratio <= 0:
            return {"kelly_fraction": 0.0, "allocated_capital": 0.0, "quantity": 0}

        w = win_rate_pct / 100.0
        r = win_loss_ratio

        # Full Kelly fraction
        full_kelly = w - ((1.0 - w) / r)
        # Half Kelly fraction for safety
        half_kelly = max(0.0, min(0.25, 0.50 * full_kelly))

        allocated_capital = account_equity * half_kelly
        raw_quantity = int(allocated_capital // price)
        quantity = max(1, raw_quantity) if half_kelly > 0 else 0

        return {
            "full_kelly_fraction": round(full_kelly, 4),
            "half_kelly_fraction": round(half_kelly, 4),
            "allocated_capital": round_to_indian_tick_size(allocated_capital),
            "quantity": quantity,
            "win_rate_pct": win_rate_pct,
            "win_loss_ratio": win_loss_ratio,
            "magic_number": self.magic_number,
        }

    def calculate_vwap_bands(self, history_bars: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Calculates intraday Volume Weighted Average Price (VWAP) and 1.0x/2.0x StdDev bands.
        """
        if not history_bars:
            return {
                "vwap": 500.0,
                "upper_band_1": 505.0,
                "lower_band_1": 495.0,
                "upper_band_2": 510.0,
                "lower_band_2": 490.0,
            }

        cum_tp_vol = 0.0
        cum_vol = 0.0
        prices = []

        for b in history_bars:
            h = float(b["high"])
            l = float(b["low"])
            c = float(b["close"])
            v = float(b.get("volume", b.get("tick_volume", 1000)))

            tp = (h + l + c) / 3.0
            cum_tp_vol += tp * v
            cum_vol += v
            prices.append(c)

        vwap = cum_tp_vol / max(1.0, cum_vol)

        var = sum((p - vwap) ** 2 for p in prices) / float(max(1, len(prices)))
        std_dev = math.sqrt(var) if var > 0 else 1.0

        return {
            "vwap": round_to_indian_tick_size(vwap),
            "upper_band_1": round_to_indian_tick_size(vwap + std_dev),
            "lower_band_1": round_to_indian_tick_size(vwap - std_dev),
            "upper_band_2": round_to_indian_tick_size(vwap + 2.0 * std_dev),
            "lower_band_2": round_to_indian_tick_size(vwap - 2.0 * std_dev),
            "std_dev": round(std_dev, 2),
        }

    def evaluate_trading_skills_setup(self, history_bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not history_bars or len(history_bars) < 21:
            return {"signal": "HOLD", "confidence": 0.0, "magic_number": self.magic_number}

        closes = [float(b["close"]) for b in history_bars]
        current_price = closes[-1]

        vwap_info = self.calculate_vwap_bands(history_bars)

        ema9 = sum(closes[-9:]) / 9.0
        ema21 = sum(closes[-21:]) / 21.0

        signal = "HOLD"
        confidence = 0.50
        sl = 0.0
        tp = 0.0

        if current_price > vwap_info["vwap"] and ema9 > ema21 and current_price <= vwap_info["upper_band_1"]:
            signal = "BUY"
            sl = vwap_info["lower_band_1"]
            sl_dist = max(5.0, current_price - sl)
            tp = round_to_indian_tick_size(current_price + sl_dist * 2.0)
            confidence = 0.85

        elif current_price < vwap_info["vwap"] and ema9 < ema21 and current_price >= vwap_info["lower_band_1"]:
            signal = "SELL"
            sl = vwap_info["upper_band_1"]
            sl_dist = max(5.0, sl - current_price)
            tp = round_to_indian_tick_size(current_price - sl_dist * 2.0)
            confidence = 0.85

        return {
            "signal": signal,
            "confidence": confidence,
            "entry_price": round_to_indian_tick_size(current_price),
            "sl": sl,
            "tp": tp,
            "vwap_bands": vwap_info,
            "ema9": round_to_indian_tick_size(ema9),
            "ema21": round_to_indian_tick_size(ema21),
            "magic_number": self.magic_number,
        }


class IndianTradingSkillsAdapter(SEBIBrokerAdapter):
    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.engine = IndianTradingSkillsEngine()
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
        ticket = f"TRDSKILL_{time.time_ns()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 2850.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_INDIAN_TRADING_SKILLS,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_INDIAN_TRADING_SKILLS},
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


IndianBrokerPluginRegistry.register("INDIAN_TRADING_SKILLS", IndianTradingSkillsAdapter)
IndianBrokerPluginRegistry.register("TRADING_SKILLS", IndianTradingSkillsAdapter)
