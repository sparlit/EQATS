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
from pprint import pprint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402

# or
# import ccxtpro as ccxt


print("CCXT Version:", ccxt.__version__)


async def main():
    exchange = ccxt.okx(
        {
            "apiKey": "YOUR_API_KEY",  # https://github.com/ccxt/ccxt/wiki/Manual#authentication
            "secret": "YOUR_API_SECRET",
            "password": "YOUR_API_PASSWORD",
            "options": {
                "defaultType": "future",
            },
        }
    )
    try:
        markets = await exchange.load_markets()
        exchange.verbose = True  # uncomment for debugging
        print("---------------------------------------------------------------")
        print("Futures balance:")
        await exchange.fetch_balance()
        print("---------------------------------------------------------------")
        print("Futures symbols:")
        print([market["symbol"] for market in markets.values() if market["future"]])
        print("---------------------------------------------------------------")
        symbol = "BTC/USDT:USDT-201225"  # a futures symbol
        exchange.market(symbol)
        print("---------------------------------------------------------------")
        type = "1"  # 1:open long 2:open short 3:close long 4:close short for futures
        side = None  # irrelevant for futures
        amount = 1  # how many contracts you want to buy or sell
        price = 17000  # limit price
        params = {
            # 'order_type': '4',  # uncomment for a market order, makes limit price irrelevant
            # 'leverage': '10',  # or '20'
        }
        await exchange.create_order(symbol, type, side, amount, price, params)
        print("Order:")
        print("---------------------------------------------------------------")
    except Exception as e:
        print(type(e).__name__, str(e))
    await exchange.close()


run(main())
