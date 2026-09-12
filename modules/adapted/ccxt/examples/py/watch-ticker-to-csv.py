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

from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
from pprint import pprint

import ccxt.pro


async def watch_ticker_continuously(exchange, symbol):
    filename = exchange.id + "-" + symbol.replace("/", "-") + ".csv"
    print("Watching", exchange.id, symbol, filename)
    keys = ["index", "exchange", "symbol", "timestamp", "open", "high", "low", "close", "baseVolume"]
    with open(filename, "w") as file:
        file.write(",".join(keys) + "\n")
    index = 0
    while True:
        try:
            ticker = await exchange.watch_ticker(symbol)
            values = [str(index), exchange.id] + [str(ticker[key]) for key in keys[2:]]
            print(*values)
            with open(filename, "a") as file:
                file.write(",".join(values) + "\n")
            index += 1
        except Exception as e:
            print(e)


async def watch_tickers_continuously(exchange_id, overrides, symbols):
    exchange_class = getattr(ccxt.pro, exchange_id)
    exchange = exchange_class(overrides)
    coroutines = [watch_ticker_continuously(exchange, symbol) for symbol in symbols]
    await gather(*coroutines)
    await exchange.close()


async def main():
    exchanges = {"binance": {"options": {"defaultType": "future"}}, "htx": {}}
    symbols = ["BTC/USDT", "ETH/USDT", "LTC/USDT", "XRP/USDT", "BCH/USDT"]
    coroutines = [watch_tickers_continuously(exchange_id, exchanges[exchange_id], symbols) for exchange_id in exchanges]
    return await gather(*coroutines)


run(main())
