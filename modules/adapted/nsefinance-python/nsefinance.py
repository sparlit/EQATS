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


import json

import urllib2


class NSEFinance:
    url = "http://nsefinance.com/api/stocks"

    def __init__(self):
        pass

    # Main Data Handler
    def _data(self, symbol=None, date=None):
        if not symbol:
            data = urllib2.urlopen(self.url).read()

        elif symbol and not date:
            url = self.url + "/" + str(symbol)
            data = urllib2.urlopen(url).read()

        elif symbol and date:
            url = self.url + "/" + str(symbol) + "/" + str(date)
            data = urllib2.urlopen(url).read()
        return data

    # Get daily result
    def get_daily_list(self):
        data = self._data()
        return json.loads(data)

    # Get by symbol and Date
    def get_by_symbol(self, symbol=None, date=None):
        if not symbol:
            msg = "Symbol not supplied"
            raise ValueError(msg)

        if not date:
            data = self._data(symbol)
            return json.loads(data)

        if symbol and date:
            data = self._data(symbol, date)
            return json.loads(data)
        return None
