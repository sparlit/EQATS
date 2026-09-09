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
from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402


async def symbol_loop(exchange, symbol):
    print("Starting the", exchange.id, "symbol loop with", symbol)
    while True:
        try:
            orderbook = await exchange.fetch_order_book(symbol)
            now = exchange.milliseconds()
            print(exchange.iso8601(now), exchange.id, symbol, orderbook["asks"][0], orderbook["bids"][0])

            # --------------------> DO YOUR LOGIC HERE <------------------

        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            break  # you can break just this one loop if it fails


async def exchange_loop(exchange_id, symbols):
    print("Starting the", exchange_id, "exchange loop with", symbols)
    exchange = getattr(ccxt, exchange_id)()
    loops = [symbol_loop(exchange, symbol) for symbol in symbols]
    await gather(*loops)
    await exchange.close()


async def main():
    exchanges = {
        "okx": ["BTC/USDT", "ETH/BTC", "ETH/USDT"],
        "binance": ["BTC/USDT", "ETH/BTC"],
        "bitfinex": ["BTC/USDT"],
    }
    loops = [exchange_loop(exchange_id, symbols) for exchange_id, symbols in exchanges.items()]
    await gather(*loops)


run(main())
