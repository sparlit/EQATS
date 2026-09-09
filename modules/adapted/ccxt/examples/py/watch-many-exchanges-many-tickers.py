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
import ccxt.pro

print("CCXT Version:", ccxt.__version__)


async def exchange_loop(exchange_id, symbols):
    exchange = getattr(ccxt.pro, exchange_id)()
    await exchange.load_markets()
    await gather(*[watch_ticker_loop(exchange, symbol) for symbol in symbols])
    await exchange.close()


async def watch_ticker_loop(exchange, symbol):
    # exchange.verbose = True  # uncomment for debugging purposes if necessary
    while True:
        try:
            ticker = await exchange.watch_ticker(symbol)
            now = exchange.milliseconds()
            print(
                exchange.iso8601(now),
                exchange.id,
                symbol,
                "bid:",
                ticker["bid"],
                "ask:",
                ticker["ask"],
                "last:",
                ticker["last"],
                "on",
                ticker["datetime"],
            )
        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            break  # you can break just this one loop if it fails


async def main():
    exchanges = {
        "binance": ["BTC/USDT", "ETH/USDT"],
        "okx": ["BTC/USD", "ETH/USD"],
    }
    loops = [exchange_loop(exchange_id, symbols) for exchange_id, symbols in exchanges.items()]
    await gather(*loops)


run(main())
