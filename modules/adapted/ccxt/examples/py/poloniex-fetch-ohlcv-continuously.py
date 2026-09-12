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

# this example shows how to fetch OHLCVs continuously, see issue #7498
# https://github.com/ccxt/ccxt/issues/7498


async def fetch_ohlcvs_continuously(exchange, timeframe, symbol, fetching_time):
    print(exchange.id, timeframe, symbol, "starting")
    all_ohlcvs = []
    limit = 1
    duration_in_seconds = exchange.parse_timeframe(timeframe)
    duration_in_milliseconds = duration_in_seconds * 1000
    now = exchange.milliseconds()
    end_time = now + fetching_time
    while now < end_time:
        since = int(now / duration_in_milliseconds) * duration_in_milliseconds
        time_to_wait = duration_in_milliseconds - now % duration_in_milliseconds + 10000  # +10 seconds buffer
        print(exchange.id, timeframe, symbol, "time now is", exchange.iso8601(now))
        print(exchange.id, timeframe, symbol, "time to wait is", time_to_wait / 1000, "seconds")
        print(exchange.id, timeframe, symbol, "sleeping till", exchange.iso8601(now + time_to_wait))
        await exchange.sleep(time_to_wait)
        print(exchange.id, timeframe, symbol, "done sleeping at", exchange.iso8601(exchange.milliseconds()))
        while True:
            try:
                ohlcvs = await exchange.fetch_ohlcv(symbol, timeframe, since, limit)
                break
            except Exception as e:
                print(type(e).__name__, e.args, str(e))  # comment if not needed
                # break  # uncomment to break it
                # pass   # uncomment to do nothing and just retry again on next iteration
                # or add your own reaction according to the purpose of your app
        print(
            exchange.id,
            timeframe,
            symbol,
            "fetched",
            len(ohlcvs),
            "candle(s), time now is",
            exchange.iso8601(exchange.milliseconds()),
        )
        print(exchange.id, timeframe, symbol, "all candles:")
        all_ohlcvs += ohlcvs
        for ohlcv in all_ohlcvs:
            print("    ", exchange.iso8601(ohlcv[0]), ohlcv[1:])
        now = exchange.milliseconds()
    return {symbol: all_ohlcvs}


async def fetch_all_ohlcvs_continuously(exchange_id, timeframe, symbols, fetching_time):
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class()
    input_coroutines = [fetch_ohlcvs_continuously(exchange, timeframe, symbol, fetching_time) for symbol in symbols]
    results = await asyncio.gather(*input_coroutines, return_exceptions=True)
    await exchange.close()
    return exchange.extend(*results)


print("CCXT version:", ccxt.__version__)

exchange_id = "poloniex"
symbols = ["ETH/BTC", "BTC/USDT"]
timeframe = "5m"
fetching_time = 15 * 60 * 1000  # stop after 15 minutes (approximately 4 iterations)
coroutine = fetch_all_ohlcvs_continuously(exchange_id, timeframe, symbols, fetching_time)
results = run(coroutine)
# results  # if you run this code in Jupyter then uncomment thisline to see the output result
