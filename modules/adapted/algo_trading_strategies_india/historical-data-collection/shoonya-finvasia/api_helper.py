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


import concurrent.futures
import time
from threading import Timer

import pandas as pd
from NorenRestApiPy.NorenApi import NorenApi

api = None


class Order:
    def __init__(
        self,
        buy_or_sell: str | None = None,
        product_type: str | None = None,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        price_type: str | None = None,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        discloseqty: int = 0,
        retention: str = "DAY",
        remarks: str = "tag",
        order_id: str | None = None,
    ):
        self.buy_or_sell = buy_or_sell
        self.product_type = product_type
        self.exchange = exchange
        self.tradingsymbol = tradingsymbol
        self.quantity = quantity
        self.discloseqty = discloseqty
        self.price_type = price_type
        self.price = price
        self.trigger_price = trigger_price
        self.retention = retention
        self.remarks = remarks
        self.order_id = None


# print(ret)


def get_time(time_string):
    data = time.strptime(time_string, "%d-%m-%Y %H:%M:%S")

    return time.mktime(data)


class ShoonyaApiPy(NorenApi):
    def __init__(self):
        NorenApi.__init__(
            self, host="https://api.shoonya.com/NorenWClientTP/", websocket="wss://api.shoonya.com/NorenWSTP/"
        )
        global api
        api = self

    def place_basket(self, orders):

        resp_err = 0
        resp_ok = 0
        result = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(self.place_order, order): order for order in orders}
            for future in concurrent.futures.as_completed(future_to_url):
                future_to_url[future]
            try:
                result.append(future.result())
            except Exception as exc:
                print(exc)
                resp_err = resp_err + 1
            else:
                resp_ok = resp_ok + 1

        return result

    def placeOrder(self, order: Order):
        return NorenApi.place_order(
            self,
            buy_or_sell=order.buy_or_sell,
            product_type=order.product_type,
            exchange=order.exchange,
            tradingsymbol=order.tradingsymbol,
            quantity=order.quantity,
            discloseqty=order.discloseqty,
            price_type=order.price_type,
            price=order.price,
            trigger_price=order.trigger_price,
            retention=order.retention,
            remarks=order.remarks,
        )
        # print(ret)
