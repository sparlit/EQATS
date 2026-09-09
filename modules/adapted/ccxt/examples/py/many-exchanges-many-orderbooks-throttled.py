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

from asyncio import gather, sleep
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run


orderbooks = {}


def handle_all_orderbooks(orderbooks):
    print("We have the following orderbooks:")
    for exchange_id, orderbooks_by_symbol in orderbooks.items():
        for symbol in orderbooks_by_symbol:
            orderbook = orderbooks_by_symbol[symbol]
            print(
                ccxt.pro.Exchange.iso8601(orderbook["timestamp"]),
                exchange_id,
                symbol,
                orderbook["asks"][0],
                orderbook["bids"][0],
            )


async def handling_loop(orderbooks):
    delay = 5
    while True:
        await sleep(delay)
        handle_all_orderbooks(orderbooks)


async def symbol_loop(exchange, symbol):
    while True:
        try:
            orderbook = await exchange.watch_order_book(symbol)
            orderbooks[exchange.id] = orderbooks.get(exchange.id, {})
            orderbooks[exchange.id][symbol] = orderbook
        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            break  # you can break just this one loop if it fails


async def exchange_loop(exchange_id, symbols):
    exchange = getattr(ccxt.pro, exchange_id)()
    loops = [symbol_loop(exchange, symbol) for symbol in symbols]
    await gather(*loops)
    await exchange.close()


async def main():
    symbols = ["BTC/USDT", "ETH/BTC"]
    # symbols = []
    exchanges = {
        "okx": [*symbols, "ETH/USDT"],
        "binance": symbols,
    }
    loops = [exchange_loop(exchange_id, symbols) for exchange_id, symbols in exchanges.items()]
    loops += [handling_loop(orderbooks)]
    await gather(*loops)


run(main())
