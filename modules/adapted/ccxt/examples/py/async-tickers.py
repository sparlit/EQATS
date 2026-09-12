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


def get_active_symbols(exchange):
    return [symbol for symbol in exchange.symbols if is_active_symbol(exchange, symbol)]


def is_active_symbol(exchange, symbol):
    return ("." not in symbol) and (("active" not in exchange.markets[symbol]) or (exchange.markets[symbol]["active"]))


async def fetch_ticker(exchange, symbol):
    ticker = await exchange.fetchTicker(symbol)
    print(exchange.id, symbol, ticker)
    return ticker


async def fetch_tickers(exchange):
    await exchange.load_markets()
    print(exchange.id, "fetching all tickers by simultaneous multiple concurrent requests")
    symbols_to_load = get_active_symbols(exchange)
    input_coroutines = [fetch_ticker(exchange, symbol) for symbol in symbols_to_load]
    tickers = await asyncio.gather(*input_coroutines, return_exceptions=True)
    for ticker, symbol in zip(tickers, symbols_to_load, strict=False):
        if not isinstance(ticker, dict):
            print(exchange.id, symbol, "error")
        else:
            print(exchange.id, symbol, "ok")
    print(exchange.id, "fetched", len(list(tickers)), "tickers")


run(fetch_tickers(ccxt.bitfinex()))
