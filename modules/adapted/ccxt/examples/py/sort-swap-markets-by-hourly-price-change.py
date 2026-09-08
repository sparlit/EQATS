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
import os
import sys
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import time
from datetime import UTC, datetime, timezone
from pprint import pprint

# -----------------------------------------------------------------------------

this_folder = os.path.dirname(os.path.abspath(__file__))
root_folder = os.path.dirname(os.path.dirname(this_folder))
sys.path.append(root_folder + "/python")
sys.path.append(this_folder)

# -----------------------------------------------------------------------------

import ccxt.async_support as ccxt  # noqa: E402

# -----------------------------------------------------------------------------

exchange = ccxt.binanceusdm()
timeframe = "1h"
ohlcvs = []


async def fetchOHLCV(symbol):
    """
    Wrapper around exchange.fetchOHLCV method
    :param str symbol: CCXT unified symbol
    :returns [float|str]: 1d array with a single ohlcv record with the market symbol appended
    """
    try:
        ohlcv = await exchange.fetchOHLCV(symbol, timeframe, None, 2)
        ohlcv[0].append(symbol)
        ohlcvs.append(ohlcv[0])
    except Exception as e:
        print(f"{symbol} failed fetchOHLCV with exception {e}")


def getPriceChangePercent(ohlcv):
    """
    Gets the price change of a market as a percentage
    :param [float] ohlcv: A single ohlcv record with the market symbol appended
    :returns [float, str]: The price change as a percent with the symbol for the market
    """
    open = ohlcv[1]
    close = ohlcv[4]
    symbol = ohlcv[6]
    priceIncrease = close - open
    increaseAsRatio = priceIncrease / open
    return [increaseAsRatio, symbol]


async def main():
    """
    Gets the price change as a percent of every market matching type over the last timeframe matching timeframe and prints a sorted list.
    The most immediate candle is ignored because it is incomplete
    """
    start = time.time()

    await exchange.load_markets()
    allSwapSymbols = [symbol for symbol in exchange.symbols if exchange.market(symbol)["swap"]]
    await asyncio.gather(*[fetchOHLCV(symbol) for symbol in allSwapSymbols])
    await exchange.close()
    priceChanges = [getPriceChangePercent(ohlcv) for ohlcv in ohlcvs]
    priceChanges.sort()

    end = time.time()
    duration = str(int((end - start) * 1000))
    now = str(datetime.now(UTC).isoformat())

    print("python", sys.version)
    print("CCXT Version:", ccxt.__version__)
    print(now + " iteration 0 passed in " + duration + " ms")
    print()


run(main())
