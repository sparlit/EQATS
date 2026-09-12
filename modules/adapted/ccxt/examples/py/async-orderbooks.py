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
import time

import ccxt
import ccxt.async_support as ccxta  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")


async def async_client(exchange, symbol):
    client = getattr(ccxta, exchange)()
    await client.load_markets()
    if symbol not in client.symbols:
        raise Exception(exchange + " does not support symbol " + symbol)
    while True:
        try:
            orderbook = await client.fetch_order_book(symbol)
            datetime = client.iso8601(client.milliseconds())
            print(datetime, client.id, symbol, orderbook["bids"][0], orderbook["asks"][0])
        except Exception as e:
            print(type(e).__name__, e.args, str(e))  # comment if not needed
            # break  # uncomment to break it
            # pass   # uncomment to do nothing and just retry again on next iteration
            # or add your own reaction according to the purpose of your app
    await client.close()


async def multi_orderbooks(exchanges, symbol):
    input_coroutines = [async_client(exchange, symbol) for exchange in exchanges]
    await asyncio.gather(*input_coroutines, return_exceptions=True)


if __name__ == "__main__":
    # Consider review request rate limit in the methods you call
    exchanges = ["kucoin", "bitfinex", "poloniex"]
    symbol = "ETH/BTC"

    run(multi_orderbooks(exchanges, symbol))
