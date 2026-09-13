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

exchange = ccxt.coinex(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET_KEY",
    }
)


# Example 1 :: Swap : fetch balance, create a limit swap order with leverage
async def example_1():
    exchange.options["defaultType"] = "swap"
    exchange.options["defaultMarginMode"] = "cross"  # or isolated
    await exchange.load_markets()

    # fetch swap balance
    balance = await exchange.fetch_balance()
    print(balance)

    # set the desired leverage (has to be made before placing the order and for a specific symbol)
    leverage = 8
    symbol = "ADA/USDT:USDT"
    await exchange.set_leverage(leverage, symbol)

    # create limit order
    symbol = "ADA/USDT:USDT"
    type = "limit"
    side = "buy"
    amount = 50
    price = 0.3
    create_order = await exchange.create_order(symbol, type, side, amount, price)
    print("Create order id:", create_order["id"])


# ------------------------------------------------------------------------------------------


# Example 2 :: Swap :: open a position and close it
async def example_2():
    exchange.options["defaultType"] = "swap"  # very important set swap as default type
    exchange.options["defaultMarginMode"] = "cross"  # or isolated
    await exchange.load_markets()

    # set the desired leverage (has to be made before placing the order and for a specific symbol)
    leverage = 3
    symbol = "ADA/USDT:USDT"
    await exchange.set_leverage(leverage, symbol)

    # create market order and open position
    symbol = "ADA/USDT:USDT"
    type = "market"
    side = "buy"
    amount = 55
    price = None
    create_order = await exchange.create_order(symbol, type, side, amount, price)
    print("Create order id:", create_order["id"])

    # check opened position
    position = await exchange.fetch_position(symbol)
    print(position)

    # Close position by issuing a market order in the opposite direction
    side = "sell"
    params = {"reduce_only": True}
    close_position_order = await exchange.createOrder(symbol, type, side, amount, price, params)
    print(close_position_order)


# ------------------------------------------------------------------------------------------


async def main():
    await example_1()
    await example_2()


run(main())
