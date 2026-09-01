"""
High-Frequency L3 Order Book & Queue Matching Engine.
Provides limit orderbook maintenance, microsecond queue position estimation,
price-time priority matching, order amendments, and execution latency simulation.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import time

class BookSide(Enum):
    BID = 'BID'
    ASK = 'ASK'

@dataclass
class LimitOrder:
    order_id: str
    symbol: str
    side: BookSide
    price: float
    quantity: float
    timestamp_ns: int
    magic_number: int = 9300001
    filled_qty: float = 0.0

@dataclass
class QueueInfo:
    order_id: str
    price: float
    queue_position_ahead_qty: float
    estimated_time_to_fill_ms: float

class HighFrequencyMatchingOrderBook:
    """
    High-Frequency Order Book supporting price-time priority order matching
    and FIFO queue position tracking adapted from hftbacktest & barter-rs.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol: str = symbol
        self.bids: Dict[float, List[LimitOrder]] = {}
        self.asks: Dict[float, List[LimitOrder]] = {}
        self.orders_by_id: Dict[str, LimitOrder] = {}

    def add_limit_order(self, order: LimitOrder) -> List[Dict[str, Any]]:
        fills: List[Dict[str, Any]] = []
        self.orders_by_id[order.order_id] = order
        if order.side == BookSide.BID:
            sorted_ask_prices = sorted(self.asks.keys())
            for ask_price in sorted_ask_prices:
                if order.price >= ask_price and order.quantity > order.filled_qty:
                    ask_queue = self.asks[ask_price]
                    remaining_ask_queue: List[LimitOrder] = []
                    for passive_order in ask_queue:
                        unfilled_bid = order.quantity - order.filled_qty
                        unfilled_ask = passive_order.quantity - passive_order.filled_qty
                        match_qty = min(unfilled_bid, unfilled_ask)
                        if match_qty > 0:
                            order.filled_qty += match_qty
                            passive_order.filled_qty += match_qty
                            fills.append({'bid_id': order.order_id, 'ask_id': passive_order.order_id, 'match_price': ask_price, 'match_qty': match_qty, 'timestamp_ns': time.time_ns()})
                        if passive_order.filled_qty < passive_order.quantity:
                            remaining_ask_queue.append(passive_order)
                        else:
                            del self.orders_by_id[passive_order.order_id]
                    if remaining_ask_queue:
                        self.asks[ask_price] = remaining_ask_queue
                    else:
                        del self.asks[ask_price]
            if order.quantity > order.filled_qty:
                if order.price not in self.bids:
                    self.bids[order.price] = []
                self.bids[order.price].append(order)
        elif order.side == BookSide.ASK:
            sorted_bid_prices = sorted(self.bids.keys(), reverse=True)
            for bid_price in sorted_bid_prices:
                if order.price <= bid_price and order.quantity > order.filled_qty:
                    bid_queue = self.bids[bid_price]
                    remaining_bid_queue: List[LimitOrder] = []
                    for passive_order in bid_queue:
                        unfilled_ask = order.quantity - order.filled_qty
                        unfilled_bid = passive_order.quantity - passive_order.filled_qty
                        match_qty = min(unfilled_ask, unfilled_bid)
                        if match_qty > 0:
                            order.filled_qty += match_qty
                            passive_order.filled_qty += match_qty
                            fills.append({'bid_id': passive_order.order_id, 'ask_id': order.order_id, 'match_price': bid_price, 'match_qty': match_qty, 'timestamp_ns': time.time_ns()})
                        if passive_order.filled_qty < passive_order.quantity:
                            remaining_bid_queue.append(passive_order)
                        else:
                            del self.orders_by_id[passive_order.order_id]
                    if remaining_bid_queue:
                        self.bids[bid_price] = remaining_bid_queue
                    else:
                        del self.bids[bid_price]
            if order.quantity > order.filled_qty:
                if order.price not in self.asks:
                    self.asks[order.price] = []
                self.asks[order.price].append(order)
        return fills

    def cancel_order(self, order_id: str) -> bool:
        if order_id not in self.orders_by_id:
            return False
        order = self.orders_by_id.pop(order_id)
        book = self.bids if order.side == BookSide.BID else self.asks
        if order.price in book:
            book[order.price] = [o for o in book[order.price] if o.order_id != order_id]
            if not book[order.price]:
                del book[order.price]
        return True

    def estimate_queue_position(self, order_id: str, avg_trades_per_sec: float=10.0) -> Optional[QueueInfo]:
        if order_id not in self.orders_by_id:
            return None
        order = self.orders_by_id[order_id]
        book = self.bids if order.side == BookSide.BID else self.asks
        if order.price not in book:
            return None
        queue = book[order.price]
        ahead_qty = 0.0
        for o in queue:
            if o.order_id == order_id:
                break
            ahead_qty += o.quantity - o.filled_qty
        est_time_ms = ahead_qty / max(1.0, avg_trades_per_sec) * 1000.0
        return QueueInfo(order_id=order_id, price=order.price, queue_position_ahead_qty=ahead_qty, estimated_time_to_fill_ms=est_time_ms)

    def get_L2_depth(self, depth: int=5) -> Dict[str, List[Dict[str, float]]]:
        sorted_bids = sorted(self.bids.keys(), reverse=True)[:depth]
        sorted_asks = sorted(self.asks.keys())[:depth]
        bid_levels = [{'price': p, 'volume': sum((o.quantity - o.filled_qty for o in self.bids[p]))} for p in sorted_bids]
        ask_levels = [{'price': p, 'volume': sum((o.quantity - o.filled_qty for o in self.asks[p]))} for p in sorted_asks]
        return {'bids': bid_levels, 'asks': ask_levels}
