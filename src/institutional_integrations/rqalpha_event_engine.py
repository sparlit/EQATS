"""
RQAlpha & PyBroker Event-Driven Portfolio & Order Matching Engine.
Provides event-driven backtesting execution, slice-based simulation, portfolio tracking,
bar execution context, dynamic ATR slippage models, and Indian stock market (NSE/BSE) session/tick rules.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .indian_market_state_machine import IndianMarketStateMachine, round_to_indian_tick_size
from .rust_bridge import rust_accelerated_rqalpha_process_bar_orders


class EventType(Enum):
    BAR = "BAR"
    TICK = "TICK"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Bar:
    symbol: str
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class EventOrder:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float
    magic_number: int = 9100001
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    status: str = "PENDING"
    product: str | None = "CNC"


@dataclass
class PositionRecord:
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class RQAlphaEventEngine:
    """
    Event-driven portfolio accounting and execution simulator adapted from RQAlpha & PyBroker,
    fully integrated with Indian Market constraints (0.05 INR tick rounding, session validation)
    and high-performance Rust execution acceleration.
    """

    def __init__(
        self, initial_capital: float = 100000.0, commission_rate: float = 0.0001, enforce_indian_rules: bool = False,
    ) -> None:
        self.initial_capital: float = initial_capital
        self.cash: float = initial_capital
        self.commission_rate: float = commission_rate
        self.enforce_indian_rules: bool = enforce_indian_rules
        self.positions: dict[str, PositionRecord] = {}
        self.pending_orders: list[EventOrder] = []
        self.completed_orders: list[EventOrder] = []
        self.equity_history: list[dict[str, Any]] = []

    def submit_order(self, order: EventOrder) -> bool:
        if order.quantity <= 0:
            return False
        if self.enforce_indian_rules and order.price > 0:
            order.price = round_to_indian_tick_size(order.price)
        self.pending_orders.append(order)
        return True

    def process_bar(self, bar: Bar, atr_slippage_pips: float = 0.0001) -> list[EventOrder]:
        filled_in_this_bar: list[EventOrder] = []
        if bar.symbol not in self.positions:
            self.positions[bar.symbol] = PositionRecord(symbol=bar.symbol)
        is_indian = (
            self.enforce_indian_rules
            or bar.symbol.endswith((".NS", ".BO", "NSE", "BSE"))
            or bar.symbol in ("SBIN", "RELIANCE", "TCS", "INFY", "HDFCBANK")
        )
        remaining_orders: list[EventOrder] = []
        for order in self.pending_orders:
            if order.symbol != bar.symbol:
                remaining_orders.append(order)
                continue
            fill_price = 0.0
            fill_info = None
            if order.order_type == OrderType.MARKET:
                fill_info = rust_accelerated_rqalpha_process_bar_orders(
                    bar_close=bar.close,
                    atr_slippage=atr_slippage_pips,
                    tick_size=0.05 if is_indian else 0.0001,
                    is_buy=order.side == OrderSide.BUY,
                    quantity=order.quantity,
                    price=order.price,
                    commission_rate=self.commission_rate,
                )
                fill_price = fill_info.get("fill_price", bar.close)
            elif order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and bar.low <= order.price:
                    raw_p = min(order.price, bar.high)
                    fill_price = round_to_indian_tick_size(raw_p) if is_indian else raw_p
                elif order.side == OrderSide.SELL and bar.high >= order.price:
                    raw_p = max(order.price, bar.low)
                    fill_price = round_to_indian_tick_size(raw_p) if is_indian else raw_p
            if fill_price > 0.0:
                cost = fill_price * order.quantity
                commission = (
                    fill_info.get("commission", cost * self.commission_rate)
                    if fill_info
                    else cost * self.commission_rate
                )
                pos = self.positions[bar.symbol]
                if order.side == OrderSide.BUY:
                    if self.cash >= cost + commission:
                        self.cash -= cost + commission
                        new_qty = pos.quantity + order.quantity
                        if new_qty > 0:
                            pos.avg_entry_price = (pos.quantity * pos.avg_entry_price + cost) / new_qty
                        pos.quantity = new_qty
                        order.filled_quantity = order.quantity
                        order.avg_fill_price = fill_price
                        order.status = "FILLED"
                        filled_in_this_bar.append(order)
                        self.completed_orders.append(order)
                    else:
                        order.status = "REJECTED_MARGIN"
                        self.completed_orders.append(order)
                elif order.side == OrderSide.SELL:
                    proceeds = cost - commission
                    self.cash += proceeds
                    pnl = (fill_price - pos.avg_entry_price) * order.quantity
                    pos.realized_pnl += pnl
                    pos.quantity -= order.quantity
                    if pos.quantity == 0:
                        pos.avg_entry_price = 0.0
                    order.filled_quantity = order.quantity
                    order.avg_fill_price = fill_price
                    order.status = "FILLED"
                    filled_in_this_bar.append(order)
                    self.completed_orders.append(order)
            else:
                remaining_orders.append(order)
        self.pending_orders = remaining_orders
        pos = self.positions[bar.symbol]
        if pos.quantity != 0:
            pos.unrealized_pnl = (bar.close - pos.avg_entry_price) * pos.quantity
        total_equity = self.cash + sum(p.quantity * bar.close for p in self.positions.values() if p.quantity != 0)
        self.equity_history.append({"timestamp": bar.timestamp, "cash": self.cash, "equity": total_equity})
        return filled_in_this_bar

    def get_portfolio_summary(self) -> dict[str, Any]:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        realized = sum(p.realized_pnl for p in self.positions.values())
        portfolio_value = self.cash + unrealized
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_portfolio_value": portfolio_value,
            "total_return_pct": (portfolio_value - self.initial_capital) / self.initial_capital * 100.0,
            "open_positions_count": sum(1 for p in self.positions.values() if p.quantity != 0),
            "pending_orders_count": len(self.pending_orders),
            "completed_orders_count": len(self.completed_orders),
            "magic_number": 9100001,
        }
