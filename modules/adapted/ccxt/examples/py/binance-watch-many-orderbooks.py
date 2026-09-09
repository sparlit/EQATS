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


import asyncio
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro as ccxt

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run

orderbooks = {}


def when_orderbook_changed(exchange_spot, symbol, orderbook):
    # this is a common handler function
    # it is called when any of the orderbook is updated
    # it has access to both the orderbook that was updated
    # as well as the rest of the orderbooks
    # ...................................................................
    print("-------------------------------------------------------------")
    print("Last updated:", exchange_spot.iso8601(exchange_spot.milliseconds()))
    # ...................................................................
    # print just one orderbook here
    # print(orderbook['datetime'], symbol, orderbook['asks'][0], orderbook['bids'][0])
    # ...................................................................
    # or print all orderbooks that have been already subscribed-to
    for symbol, orderbook in orderbooks.items():
        print(orderbook["datetime"], symbol, orderbook["asks"][0], orderbook["bids"][0])


async def watch_one_orderbook(exchange_spot, symbol):
    # a call cost of 1 in the queue of subscriptions
    # means one subscription per exchange.rateLimit milliseconds
    your_delay = 1
    await exchange_spot.throttle(your_delay)
    while True:
        try:
            orderbook = await exchange_spot.watch_order_book(symbol)
            orderbooks[symbol] = orderbook
            when_orderbook_changed(exchange_spot, symbol, orderbook)
        except Exception as e:
            print(type(e).__name__, str(e))


async def watch_some_orderbooks(exchange_spot, symbol_list):
    loops = [watch_one_orderbook(exchange_spot, symbol) for symbol in symbol_list]
    # let them run, don't for all tasks cause they execute asynchronously
    # don't print here
    await asyncio.gather(*loops)


async def main():
    exchange_spot = ccxt.binance()
    await exchange_spot.load_markets()
    await watch_some_orderbooks(exchange_spot, ["ZEN/USDT", "RUNE/USDT", "AAVE/USDT", "SNX/USDT"])
    await exchange_spot.close()


run(main())
