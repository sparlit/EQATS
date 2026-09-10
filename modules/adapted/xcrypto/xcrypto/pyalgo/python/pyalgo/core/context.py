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


from typing import Dict, Union

from pyalgo import *

from .trd import *


class Context(ContextBase):
    """"""

    def __init__(self, addr: str, session_id: int, name: str, trading: bool):
        self.session = Session(addr, session_id, name, trading)

        self.tradings: dict[str, Tradable] = {}
        self.subscriptions: dict[str, DepthSubscription | BarSubscription] = {}

    @property
    def id(self):
        return self.session.id

    @property
    def name(self):
        return self.session.name

    @property
    def trading(self):
        return self.session.trading

    @property
    def is_login(self):
        return self.session.is_login

    def connect(self):
        self.session.connect()

    def on_market(self, data: Depth | Kline):
        if sub := self.subscriptions.get(data.stream):
            sub.on_market(data)

    def on_order(self, order: Order):
        if trading := self.tradings.get(order.symbol):
            trading.on_order(order)

    def subscribe(self, symbol: str, stream: str) -> DepthSubscription | BarSubscription:
        if symbol in self.tradings:
            msg = f"Duplicate subscribe {symbol}"
            raise Exception(msg)

        sub = self.session.subscribe(symbol, stream)
        key = symbol + "@" + stream

        if stream.startswith("kline"):
            bar = BarSubscription(sub, self)
            self.subscriptions[key] = bar
            self.tradings[symbol] = bar

            return bar

        if stream.startswith("depth") or stream == "bbo":
            depth = DepthSubscription(sub, self)
            self.subscriptions[key] = depth
            self.tradings[symbol] = depth

            return depth

        msg = f"Unsupported stream {stream}"
        raise Exception(msg)

    def process(self):
        if event := self.session.process():
            match event.event_type:
                case EventType.Depth | EventType.Kline:
                    self.on_market(event.data)

                case EventType.Order:
                    self.on_order(event.data)

            return event
        return None

    def add_order(
        self,
        symbol: str,
        price: float,
        quantity: float,
        side: Side,
        order_type: OrderType,
        tif: Tif,
    ) -> Optional[Order]:
        return self.session.add_order(symbol, price, quantity, side, order_type, tif)

    def cancel(self, symbol: str, order_id: int):
        self.session.cancel(symbol, order_id)
