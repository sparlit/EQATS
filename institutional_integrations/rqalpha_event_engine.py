"""
RQAlpha & PyBroker Event-Driven Portfolio & Order Matching Engine.
Provides event-driven backtesting execution, slice-based simulation, portfolio tracking,
bar execution context, and dynamic ATR slippage models.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional
import math


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


@dataclass
class PositionRecord:
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class RQAlphaEventEngine:
    """
    Event-driven portfolio accounting and execution simulator adapted from RQAlpha & PyBroker.
    """

    def __init__(self, initial_capital: float = 100000.0, commission_rate: float = 0.0001):
        self.initial_capital: float = initial_capital
        self.cash: float = initial_capital
        self.commission_rate: float = commission_rate
        self.positions: Dict[str, PositionRecord] = {}
        self.pending_orders: List[EventOrder] = []
        self.completed_orders: List[EventOrder] = []
        self.equity_history: List[Dict[str, Any]] = []

    def submit_order(self, order: EventOrder) -> bool:
        if order.quantity <= 0:
            return False
        self.pending_orders.append(order)
        return True

    def process_bar(self, bar: Bar, atr_slippage_pips: float = 0.0001) -> List[EventOrder]:
        filled_in_this_bar: List[EventOrder] = []
        if bar.symbol not in self.positions:
            self.positions[bar.symbol] = PositionRecord(symbol=bar.symbol)

        remaining_orders: List[EventOrder] = []
        for order in self.pending_orders:
            if order.symbol != bar.symbol:
                remaining_orders.append(order)
                continue

            fill_price = 0.0
            if order.order_type == OrderType.MARKET:
                # Add ATR slippage
                if order.side == OrderSide.BUY:
                    fill_price = bar.close + atr_slippage_pips
                else:
                    fill_price = bar.close - atr_slippage_pips
            elif order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and bar.low <= order.price:
                    fill_price = min(order.price, bar.high)
                elif order.side == OrderSide.SELL and bar.high >= order.price:
                    fill_price = max(order.price, bar.low)

            if fill_price > 0.0:
                cost = fill_price * order.quantity
                commission = cost * self.commission_rate
                pos = self.positions[bar.symbol]

                if order.side == OrderSide.BUY:
                    if self.cash >= (cost + commission):
                        self.cash -= (cost + commission)
                        new_qty = pos.quantity + order.quantity
                        if new_qty > 0:
                            pos.avg_entry_price = ((pos.quantity * pos.avg_entry_price) + cost) / new_qty
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

        # Update position unrealized PnL
        pos = self.positions[bar.symbol]
        if pos.quantity != 0:
            pos.unrealized_pnl = (bar.close - pos.avg_entry_price) * pos.quantity

        # Record equity
        total_equity = self.cash + sum(
            p.quantity * bar.close for p in self.positions.values() if p.quantity != 0
        )
        self.equity_history.append({
            "timestamp": bar.timestamp,
            "cash": self.cash,
            "equity": total_equity
        })

        return filled_in_this_bar

    def get_portfolio_summary(self) -> Dict[str, Any]:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        realized = sum(p.realized_pnl for p in self.positions.values())
        portfolio_value = self.cash + unrealized
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_portfolio_value": portfolio_value,
            "total_return_pct": ((portfolio_value - self.initial_capital) / self.initial_capital) * 100.0,
            "open_positions_count": sum(1 for p in self.positions.values() if p.quantity != 0),
            "pending_orders_count": len(self.pending_orders),
            "completed_orders_count": len(self.completed_orders),
        }
