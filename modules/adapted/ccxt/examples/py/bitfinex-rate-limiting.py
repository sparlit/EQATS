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

import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

symbol = "ETH/BTC"

exchange = ccxt.bitfinex(
    {
        # BITFINEX RATELIMITS DON'T CORRESPOND TO THEIR DOCUMENTATION!
        # their actual rate limit is significantly more strict than documented!
        "rateLimit": 3000,  # once every 3 seconds, 20 times per minute – will work
        # this is their documented ratelimit according to this page:
        # https://docs.bitfinex.com/v1/reference#rest-public-orderbook
        # 'rateLimit': 1000,  # once every second, 60 times per minute – won't work, will throw DDoSProtection
    }
)

for i in range(100):
    print("--------------------------------------------------------------------")
    print(i)
    print("sent:", exchange.iso8601(exchange.milliseconds()))
    orderbook = exchange.fetch_order_book(symbol)
    print(
        "received:",
        exchange.iso8601(exchange.milliseconds()),
        "bid:",
        orderbook["bids"][0],
        "ask:",
        orderbook["asks"][0],
    )
