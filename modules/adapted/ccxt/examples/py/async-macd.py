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
import os
import sys

import pandas as pd
import pandas_ta as ta

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402

# -----------------------------------------------------------------------------

print("CCXT Version:", ccxt.__version__)

# -----------------------------------------------------------------------------


async def run_ohlcv_loop(exchange, symbol, timeframe, limit):
    since = None
    fast = 12
    slow = 26
    signal = 9
    while True:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            if len(ohlcv):
                df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

                macd = df.ta.macd(fast=fast, slow=slow, signal=signal)
                df = pd.concat([df, macd], axis=1)
                print("----------------------------------------------------------")
                print(exchange.iso8601(exchange.milliseconds()), symbol, timeframe)
                print(df[-signal:])
        except Exception as e:
            print(type(e).__name__, str(e))


async def main():
    exchange = ccxt.binance()
    timeframe = "1m"
    limit = 50
    symbols = [
        "BTC/USDT",
        "ETH/USDT",
    ]
    loops = [run_ohlcv_loop(exchange, symbol, timeframe, limit) for symbol in symbols]
    await gather(*loops)
    await exchange.close()


run(main())
