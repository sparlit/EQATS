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
import ccxt.pro


async def loop(exchange, symbol, n):
    i = 0
    while True:
        try:
            orderbook = await exchange.watch_order_book(symbol)
            # print every 100th bidask to avoid wasting CPU cycles on printing
            if not i % 100:
                # i = how many updates there were in total
                # n = the number of the pair to count subscriptions
                now = exchange.milliseconds()
                print(exchange.iso8601(now), n, symbol, i, orderbook["asks"][0], orderbook["bids"][0])
            i += 1
        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            # break  # you can also break just this one loop if it fails


async def main():
    exchange = ccxt.pro.kraken()
    await exchange.load_markets()
    markets = list(exchange.markets.values())
    symbols = [market["symbol"] for market in markets if not market["darkpool"]]
    await asyncio.gather(*[loop(exchange, symbol, n) for n, symbol in enumerate(symbols)])
    await exchange.close()


run(main())
