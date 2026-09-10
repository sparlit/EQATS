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

exchange = ccxt.htx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET_KEY",
    }
)


# Example 1 :: Swap : fetch balance, open a position and close it using BBO price
async def example_1():
    await exchange.load_markets(True)

    # fetch swap balance
    balance = await exchange.fetch_balance()
    print(balance)

    # create market order and open position
    symbol = "ADA/USDT:USDT"
    # type = 'opponent' means it will use BB0 (the best bid or offer on the Exchange) as the price, htx does not support "market"
    # other types available are: opponent_fok, optimal_5, optimal_10, optimal_20, etc, etc
    # you can check all the types available in the docs: https://huobiapi.github.io/docs/usdt_swap/v1/en/#cross-place-an-order
    type = "opponent"
    side = "buy"
    amount = 1
    price = None
    create_order = await exchange.create_order(symbol, type, side, amount, price)
    print("Create order id:", create_order["id"])

    # check opened position
    symbols = [symbol]
    positions = await exchange.fetch_positions(symbols)
    print(positions)

    # Close position by issuing a order in the opposite direction
    side = "sell"
    params = {"reduceOnly": True}
    close_position_order = await exchange.createOrder(symbol, type, side, amount, price, params)
    print(close_position_order)


# -------------------------------------------------------------------------------------------


async def main():
    try:
        await example_1()
    except Exception as e:
        print(e)
    await exchange.close()


run(main())
