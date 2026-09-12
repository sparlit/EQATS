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

print("CCXT Version:", ccxt.__version__)

exchange_ids = ["binance", "okx", "gate", "htx", "bitget"]
symbols = ["BTC/USDT", "ETH/USDT", "LTC/USDT", "XRP/USDT"]


async def fetch_price(exchange, symbol):
    try:
        ticker = await exchange.fetch_ticker(symbol)
        return [
            symbol,
            # we use last traded price for this example
            # https://github.com/ccxt/ccxt/wiki/Manual#price-tickers
            # https://github.com/ccxt/ccxt/wiki/Manual#ticker-structure
            ticker["last"],
            "at",
            exchange.id,
        ]
    except Exception as e:
        print(type(e).__name__, str(e))
        return [symbol, "not available at", exchange.id]


async def compare_symbol(exchanges, symbol):
    coroutines = [fetch_price(exchange, symbol) for exchange in exchanges]
    results = await gather(*coroutines)
    print()  # spacing line
    for result in results:
        print(*result)
    print()  # spacing line


async def main():
    exchanges = [getattr(ccxt, exchange_id)() for exchange_id in exchange_ids]
    # https://github.com/ccxt/ccxt/wiki/Manual#loading-markets
    load_markets = [exchange.load_markets() for exchange in exchanges]
    print("Loading markets...")
    await gather(*load_markets)
    print("Done loading markets.")
    print("Loading tickers...")
    coroutines = [compare_symbol(exchanges, symbol) for symbol in symbols]
    await gather(*coroutines)
    close_all = [exchange.close() for exchange in exchanges]
    await gather(*close_all)


if __name__ == "__main__":
    run(main())
