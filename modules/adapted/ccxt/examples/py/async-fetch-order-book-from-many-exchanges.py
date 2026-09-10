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
from pprint import pprint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402

exchange_ids = ["binance", "kucoin", "htx"]
symbol = "ETH/BTC"


async def loop(exchange_id, symbol):

    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class()
    orderbook = {}
    try:
        await exchange.load_markets()
        # exchange.verbose = True  # uncomment for debugging purposes
        orderbook = await exchange.fetch_order_book(symbol)
    except Exception as e:
        print(type(e).__name__, str(e))
    await exchange.close()
    return exchange.extend(
        orderbook,
        {
            "exchange_id": exchange_id,
            "symbol": symbol,
        },
    )


async def run(exchange_ids, symbol):
    coroutines = [loop(exchange_id, symbol) for exchange_id in exchange_ids]
    return await asyncio.gather(*coroutines)


main = run(exchange_ids, symbol)
results = run(main)
for result in results:
    bids = result["bids"]
    asks = result["asks"]
    print(
        result["exchange_id"],
        result["symbol"],
        "top bid",
        bids[0],
        "of",
        len(bids),
        "bids,",
        "top ask",
        asks[0],
        "of",
        len(asks),
        "asks",
    )
