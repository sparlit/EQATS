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
from random import randint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.binance(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET_KEY",
    }
)

exchange = ccxt.binance(
    {
        "apiKey": os.environ["BINANCE_APIKEY"],
        "secret": os.environ["BINANCE_SECRET"],
    }
)

# You can read more about spot trailing orders here:
# https://github.com/binance/binance-spot-api-docs/blob/master/faqs/trailing-stop-faq.md


# Example 1: Spot : trailing spot loss
async def example_1():
    await exchange.load_markets(True)

    # create STOP_LOSS_LIMIT BUY with a trailing stop of 5%.
    symbol = "LTC/USDT"
    type = "STOP_LOSS_LIMIT"
    side = "buy"
    amount = 0.4
    price = 25
    params = {
        "trailingDelta": 500,  # 5% in BIPS
    }
    exchange.verbose = True
    create_order = await exchange.create_order(symbol, type, side, amount, price, params)
    print("Create order id:", create_order["id"])

    # cancel created order
    canceled_order = await exchange.cancel_order(create_order["id"], symbol)
    print(canceled_order)

    await exchange.close()


# -------------------------------------------------------------------------------------------


# Example 2: Spot : TAKE_PROFIT_LIMIT BUY order
async def example_2():
    await exchange.load_markets(True)

    # create TAKE_PROFIT_LIMIT BUY with a trailing stop of 5%.
    symbol = "LTC/USDT"
    type = "TAKE_PROFIT_LIMIT"
    side = "buy"
    amount = 0.2
    price = 70
    params = {
        "trailingDelta": 250  # 2.5% in BIPS
    }
    exchange.verbose = True
    create_order = await exchange.create_order(symbol, type, side, amount, price, params)
    print("Create order id:", create_order["id"])

    # cancel created order
    canceled_order = await exchange.cancel_order(create_order["id"], symbol)
    print(canceled_order)

    await exchange.close()


# -------------------------------------------------------------------------------------------


async def main():
    try:
        # await example_1()
        await example_2()
    except Exception as e:
        print(e)
    await exchange.close()


run(main())
