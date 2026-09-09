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

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402


async def work(exchange_id):

    # create it once per program lifetime
    exchange = getattr(ccxt, exchange_id)()

    print(exchange_id, "loaded")

    try:
        # load markets once, first and foremost
        # https://github.com/ccxt/ccxt/wiki/Manual#loading-markets
        await exchange.load_markets()

        # use the same exchange instance to iterate over loaded symbols
        # https://github.com/ccxt/ccxt/wiki/Manual#symbols-and-market-ids

        for symbol in exchange.symbols:
            try:
                # fetch the orderbook for each next symbol
                await exchange.fetch_order_book(symbol)

                # ADD YOUR SUCCESS HANDLING HERE
                print(exchange_id, "fetched", symbol, "orderbook")

            except Exception as e:
                # ADD YOUR ERROR HANDLING HERE
                # https://github.com/ccxt/ccxt/wiki/Manual#error-handling
                print(exchange_id, "could not fetch", symbol, "orderbook:", type(e).__name__)

    except Exception as e:
        # ADD YOUR ERROR HANDLING HERE
        print(exchange_id, "could not load markets:", type(e).__name__)

    # when you're done, don't forget to close the exchange instance properly
    # otherwise you will get "Unclosed client session" exception
    await exchange.close()


async def main():

    # https://stackoverflow.com/questions/48483348/limited-concurrency-with-asyncio
    max_concurrency = 5  # how many exchanges at once

    tasks = set()
    asyncio.get_running_loop()
    # loop over all exchanges
    for exchange_id in ccxt.exchanges:
        # wait for some exchange to finish before adding a new one
        if len(tasks) >= max_concurrency:
            _done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        tasks.add(asyncio.create_task(work(exchange_id)))

    # wait for the remaining exchanges to finish
    await asyncio.wait(tasks)


run(main())
