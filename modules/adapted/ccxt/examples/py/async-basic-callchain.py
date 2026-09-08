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

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402


async def run_all_exchanges(exchange_ids):
    results = {}

    for exchange_id in exchange_ids:
        exchange = getattr(ccxt, exchange_id)(
            {
                "options": {
                    "useWebapiForFetchingFees": False,
                }
            }
        )

        symbol = "ETH/BTC"
        print("Exchange:", exchange_id)

        print(exchange_id, "symbols:")
        markets = await load_markets(exchange, symbol)  # ←----------- STEP 1
        print(list(markets.keys()))

        print(symbol, "ticker:")
        ticker = await fetch_ticker(exchange, symbol)  # ←------------ STEP 2
        print(ticker)

        print(symbol, "orderbook:")
        orderbook = await fetch_orderbook(exchange, symbol)  # ←------ STEP 3
        print(orderbook)

        await exchange.close()  # ←----------- LAST STEP GOES AFTER ALL CALLS

        results[exchange_id] = ticker

    return results


async def load_markets(exchange, symbol):
    try:
        return await exchange.load_markets()
    except ccxt.BaseError as e:
        print(type(e).__name__, str(e), str(e.args))
        raise


async def fetch_ticker(exchange, symbol):
    try:
        return await exchange.fetch_ticker(symbol)
    except ccxt.BaseError as e:
        print(type(e).__name__, str(e), str(e.args))
        raise


async def fetch_orderbook(exchange, symbol):
    try:
        return await exchange.fetch_order_book(symbol)
    except ccxt.BaseError as e:
        print(type(e).__name__, str(e), str(e.args))
        raise


if __name__ == "__main__":
    exchange_ids = ["bitfinex", "okx", "exmo"]
    exchanges = []
    results = run(run_all_exchanges(exchange_ids))
    print([(exchange_id, ticker) for exchange_id, ticker in results.items()])
