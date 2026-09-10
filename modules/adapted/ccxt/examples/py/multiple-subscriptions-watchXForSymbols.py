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
from random import randint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.pro as ccxt  # noqa: E402

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.binance({})


async def watch_multiple_trades(symbols):
    while True:
        trades = await exchange.watch_trades_for_symbols(symbols)
        print(f"trade: {trades[0]['symbol'], trades[0]['price']}")


async def watch_multiple_orderbooks(symbols):
    while True:
        orderbooks = await exchange.watch_order_book_for_symbols(symbols)
        print(f"orderbook bid: {orderbooks['symbol']}{orderbooks['bids'][0]}")


async def watch_multiple_ohlcv(symbols):
    while True:
        ohlcv = await exchange.watch_ohlcv_for_symbols(symbols)
        print(f"ohlcv: {ohlcv}")


async def example_1():

    await asyncio.gather(
        watch_multiple_trades(["BTC/USDT", "ADA/USDT", "ETH/USDT"]),
        watch_multiple_orderbooks(["BTC/USDT", "ETH/USDT"]),
        watch_multiple_ohlcv([["BTC/USDT", "1m"], ["LTC/USDT", "1m"]]),
    )


# -------------------------------------------------------------------------------------------


async def main():
    try:
        await example_1()
    except Exception as e:
        print(e)
    await exchange.close()


run(main())
