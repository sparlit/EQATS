"""
Nautilus Trader Integration Core.
Provides Fixed Risk Sizing Engine, Asynchronous Typed Event Dispatcher,
and Order Routing Pre-Trade Risk Guard.
"""

import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("NautilusTraderEngine")

class NautilusFixedRiskSizer:
    """
    Fixed-Risk Position Sizing Engine.
    Calculates exact order quantity based on account equity, risk percentage, entry price,
    stop loss price, exchange rate, commission rate, and minimum unit batch size.
    """
    def calculate_position_size(
        self,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_loss_price: float,
        tick_value: float = 1.0,
        tick_size: float = 0.0001,
        commission_rate: float = 0.0,
        exchange_rate: float = 1.0,
        min_qty: float = 0.01,
        max_qty: float = 50.0,
        step_qty: float = 0.01
    ) -> float:
        if equity <= 0 or risk_pct <= 0 or entry_price <= 0 or stop_loss_price <= 0:
            return min_qty

        sl_distance = abs(entry_price - stop_loss_price)
        if sl_distance <= 0:
            return min_qty

        risk_amount = (equity * (risk_pct / 100.0)) * exchange_rate
        num_ticks = sl_distance / (tick_size if tick_size > 0 else 0.0001)
        raw_qty = risk_amount / ((num_ticks * tick_value) + (entry_price * commission_rate))

        # Quantize to step_qty
        steps = math.floor(raw_qty / step_qty)
        quantized_qty = steps * step_qty
        return round(max(min_qty, min(max_qty, quantized_qty)), 2)

class NautilusOrderRoutingGuard:
    """
    Pre-Trade Risk & Exposure Order Routing Guard.
    """
    def __init__(self, max_account_exposure: float = 100000.0, max_open_orders: int = 10):
        self.max_account_exposure = max_account_exposure
        self.max_open_orders = max_open_orders

    def validate_order(self, symbol: str, action: str, quantity: float, price: float, current_open_orders: int = 0) -> Dict[str, Any]:
        if current_open_orders >= self.max_open_orders:
            return {"allowed": False, "reason": f"Max open orders limit reached ({self.max_open_orders})"}

        order_notional = quantity * price
        if order_notional > self.max_account_exposure:
            return {"allowed": False, "reason": f"Order notional {order_notional:.2f} exceeds max limit {self.max_account_exposure:.2f}"}

        return {"allowed": True, "reason": "APPROVED"}
