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

from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import os
import sys
from pprint import pprint
from random import randint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.pro as ccxt  # noqa: E402

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.bybit(
    {
        # 'apiKey': 'YOUR_API_KEY',
        # 'secret': 'YOUR_SECRET_KEY',
    }
)

cache = {}  # in this example we will save markets cache in this variable, but it can be saved in a file or database

# We should use this strategy, when we need to recreate the exchange instance
# multiple times, but we don't want to reload the cache every time
# to avoid the extra time and resources needed to load the markets cache


async def save_markets_cache():
    global cache
    before = exchange.milliseconds()

    markets = await exchange.load_markets()

    after = exchange.milliseconds()

    print("Time to load markets:", after - before, "ms")

    currencies = exchange.currencies

    cache["markets"] = markets
    cache["currencies"] = currencies


async def instantiate_with_cache():
    global cache

    new_instance = ccxt.bybit({"markets": cache["markets"], "currencies": cache["currencies"]})

    before = exchange.milliseconds()

    await new_instance.load_markets()

    after = exchange.milliseconds()

    print("Time to load markets with cache:", after - before, "ms")  # as you can see, it is instanteous


async def main():
    try:
        await save_markets_cache()

        await instantiate_with_cache()

    except Exception as e:
        print(e)
    await exchange.close()


run(main())


# it should output something like this
# CCXT Version: 4.4.38
# Time to load markets: 1582 ms
# Time to load markets with cache: 0 ms
