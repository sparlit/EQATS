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

symbol = "ETH/BTC"


def sync_client(exchange_id):
    orderbook = None
    exchange = getattr(ccxt, exchange_id)()
    try:
        exchange.load_markets()
        market = exchange.market(symbol)
        orderbook = exchange.fetch_order_book(market["symbol"])
    except Exception as e:
        print(type(e).__name__, str(e))
    return {"exchange": exchange.id, "orderbook": orderbook}


async def async_client(exchange_id):
    orderbook = None
    exchange = getattr(ccxta, exchange_id)()
    try:
        await exchange.load_markets()
        market = exchange.market(symbol)
        orderbook = await exchange.fetch_order_book(market["symbol"])
    except Exception as e:
        print(type(e).__name__, str(e))
    await exchange.close()
    return {"exchange": exchange.id, "orderbook": orderbook}


async def multi_orderbooks(exchanges):
    input_coroutines = [async_client(exchange) for exchange in exchanges]
    return await asyncio.gather(*input_coroutines, return_exceptions=True)


if __name__ == "__main__":
    # Consider review request rate limit in the methods you call
    exchanges = ["kucoin", "bitfinex", "poloniex", "htx"]

    tic = time.time()
    a = run(multi_orderbooks(exchanges))
    print("async call spend:", time.time() - tic)

    time.sleep(1)

    tic = time.time()
    a = [sync_client(exchange) for exchange in exchanges]
    print("sync call spend:", time.time() - tic)
