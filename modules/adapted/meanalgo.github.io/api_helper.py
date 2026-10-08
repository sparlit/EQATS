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


import time

from NorenRestApiPy.NorenApi import NorenApi


class SymbolItem:
    def __init__(self):
        self.df = None
        self.key = None
        self.counter = 0
        self.lasttime = 0


def get_time(time_string):
    data = time.strptime(time_string, "%d-%m-%Y %H:%M:%S")

    return time.mktime(data)


class ShoonyaApiPy(NorenApi):
    def __init__(self):
        NorenApi.__init__(
            self,
            host="https://shoonyatrade.finvasia.com/NorenWClientTP/",
            websocket="wss://shoonyatrade.finvasia.com/NorenWSTP/",
            eodhost="https://shoonya.finvasia.com/chartApi/getdata/",
        )
