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


from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

import ccxt.async_support as ccxt

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run

print("CCXT Version:", ccxt.__version__)

# This example demonstrates how to execute multiple requests asynchronously.
# The requests will be executed in parallel independently of each other.
# In order to let them run in parallel the user has to disable the rate limiter.
# Disabling the rate limiter is not recommended, unless you really know
# what you are doing! If you are too aggressive with your requests and
# you don't do proper request timing precisely, the exchange can ban you!
# https://github.com/ccxt/ccxt/wiki/
# https://github.com/ccxt/ccxt/wiki/Manual
# https://github.com/ccxt/ccxt/wiki/Manual#rate-limit


async def main():
    exchange = ccxt.okx(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            "enableRateLimit": False,  # not recommended
        }
    )
    await exchange.load_markets()
    # exchange.verbose = True  # uncomment for debugging purposes
    symbol = "BTC/USDT"
    loops = [exchange.fetch_balance(), exchange.fetch_order_book(symbol), exchange.fetch_open_orders()]
    results = await gather(*loops)
    print("Balance:")
    print(results[0])
    print("------------------------------------------------------------------")
    print(symbol, "orderbook:")
    print(results[1])
    print("------------------------------------------------------------------")
    print("Open orders:")
    print(results[2])
    await exchange.close()


run(main())
