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

import asyncio
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import os
import sys

# ------------------------------------------------------------------------------

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root + "/python")

# ------------------------------------------------------------------------------

import ccxt.pro

print("CCXT Version:", ccxt.pro.__version__)

orderbooks = {}


def handle_all_orderbooks(exchange, orderbooks, spot, future):
    if spot in orderbooks and future in orderbooks:
        spot_order_book = orderbooks[spot]
        future_order_book = orderbooks[future]
        timestamp = exchange.milliseconds()
        spot_lag = abs(timestamp - spot_order_book["timestamp"]) if spot_order_book["timestamp"] else 10000
        future_lag = abs(timestamp - future_order_book["timestamp"]) if future_order_book["timestamp"] else 10000
        if spot_lag >= 10000 or future_lag >= 10000:
            print("Lag > 10 seconds")


async def symbol_loop(exchange, symbol, spot, future):
    while True:
        try:
            orderbook = await exchange.watch_order_book(symbol)
            orderbooks[symbol] = orderbook
            print(exchange.id, f"{symbol:13s}", orderbook["datetime"], orderbook["asks"][0], orderbook["bids"][0])
            #
            # here you can do what you want
            # with the most recent versions of each orderbook you have so far
            #
            # you can also wait until all of them are available
            # by just looking into all the orderbooks and counting them
            #
            # we just print them here to keep this example simple
            #
            handle_all_orderbooks(exchange, orderbooks, spot, future)
        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            break  # you can break just this one loop if it fails


async def main():
    spot = "BTC/USDT"
    future = "BTC/USDT:USDT"
    exchange = ccxt.pro.bitmart()
    loops = [
        symbol_loop(exchange, spot, spot, future),
        symbol_loop(exchange, future, spot, future),
    ]
    await asyncio.gather(*loops)
    await exchange.close()


run(main())
