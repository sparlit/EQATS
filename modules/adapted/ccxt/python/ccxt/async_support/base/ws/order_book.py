import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-

import sys

from ccxt import Exchange
from ccxt.async_support.base.ws import order_book_side


class OrderBook(dict):
    def __init__(self, snapshot=None, depth=None):
        if snapshot is None:
            snapshot = {}
        self.cache = []
        depth = depth or sys.maxsize
        defaults = {
            "bids": [],
            "asks": [],
            "timestamp": None,
            "datetime": None,
            "nonce": None,
            "symbol": None,
        }
        # do not mutate snapshot
        defaults.update(snapshot)
        if not isinstance(defaults["asks"], order_book_side.OrderBookSide):
            defaults["asks"] = order_book_side.Asks(defaults["asks"], depth)
        if not isinstance(defaults["bids"], order_book_side.OrderBookSide):
            defaults["bids"] = order_book_side.Bids(defaults["bids"], depth)
        defaults["datetime"] = Exchange.iso8601(defaults.get("timestamp"))
        # merge to self
        super().__init__(defaults)

    def limit(self):
        self["asks"].limit()
        self["bids"].limit()
        return self

    def reset(self, snapshot=None):
        if snapshot is None:
            snapshot = {}
        self["asks"]._index.clear()
        self["asks"].clear()
        for ask in snapshot.get("asks", []):
            self["asks"].storeArray(ask)
        self["bids"]._index.clear()
        self["bids"].clear()
        for bid in snapshot.get("bids", []):
            self["bids"].storeArray(bid)
        self["nonce"] = snapshot.get("nonce")
        self["timestamp"] = snapshot.get("timestamp")
        self["datetime"] = Exchange.iso8601(self["timestamp"])
        self["symbol"] = snapshot.get("symbol")
        # prediction-market identity — only attach when present, so crypto books are unchanged
        if "outcome" in snapshot:
            self["outcome"] = snapshot.get("outcome")
            self["outcomeId"] = snapshot.get("outcomeId")
            self["market"] = snapshot.get("market")
            # prediction books are keyed by `outcome`; drop the unused `symbol` to match the REST shape
            self.pop("symbol", None)

    def copy(self):
        snapshot = {}
        if "outcome" in self:
            snapshot["outcome"] = self.get("outcome")
            snapshot["outcomeId"] = self.get("outcomeId")
            snapshot["market"] = self.get("market")
        else:
            snapshot["symbol"] = self.get("symbol")
        copy = self.__class__(snapshot, self["asks"]._depth)
        copy["asks"] = self["asks"].copy()
        copy["bids"] = self["bids"].copy()
        copy["nonce"] = self.get("nonce")
        copy["timestamp"] = self.get("timestamp")
        copy["datetime"] = self.get("datetime")
        return copy

    def update(self, snapshot):
        nonce = snapshot.get("nonce")
        if nonce is not None and self["nonce"] is not None and nonce < self["nonce"]:
            return self
        self.reset(snapshot)
        return None


# -----------------------------------------------------------------------------
# overwrites absolute volumes at price levels
# or deletes price levels based on order counts (3rd value in a bidask delta)


class CountedOrderBook(OrderBook):
    def __init__(self, snapshot=None, depth=None):
        if snapshot is None:
            snapshot = {}
        copy = Exchange.extend(
            snapshot,
            {
                "asks": order_book_side.CountedAsks(snapshot.get("asks", []), depth),
                "bids": order_book_side.CountedBids(snapshot.get("bids", []), depth),
            },
        )
        super().__init__(copy, depth)


# -----------------------------------------------------------------------------
# indexed by order ids (3rd value in a bidask delta)


class IndexedOrderBook(OrderBook):
    def __init__(self, snapshot=None, depth=None):
        if snapshot is None:
            snapshot = {}
        copy = Exchange.extend(
            snapshot,
            {
                "asks": order_book_side.IndexedAsks(snapshot.get("asks", []), depth),
                "bids": order_book_side.IndexedBids(snapshot.get("bids", []), depth),
            },
        )
        super().__init__(copy, depth)
