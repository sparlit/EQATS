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

exchange = ccxt.bybit(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET_KEY",
    }
)

# exchange.set_sandbox_mode(True)  # enable sandbox mode

# -------------------------------------------------------------------------------------------


# Example 1 :: Swap : open position and set trailing stop and close it
async def example_2():
    exchange.options["defaultType"] = "swap"  # very important set swap as default type
    await exchange.load_markets()

    symbol = "LTC/USDT:USDT"
    market = exchange.market(symbol)

    # fetch swap balance
    balance = await exchange.fetch_balance()
    print(balance)

    # set trailing stop

    # create market order and open position
    type = "market"
    side = "buy"
    amount = 0.1
    price = None
    create_order = await exchange.create_order(symbol, type, side, amount, price)
    print("Create order id:", create_order["id"])

    # set trailing stop
    trailing_stop = 30  # YOUR TRAILING STOP
    rawSide = "Buy"  # or 'Sell'
    params = {"symbol": market["id"], "side": rawSide, "trailing_stop": trailing_stop}
    trailing_response = await exchange.privatePostPrivateLinearPositionTradingStop(params)
    print(trailing_response)

    # check opened position
    symbols = [symbol]
    positions = await exchange.fetch_positions(symbols)
    print(positions)

    # Close position by issuing a order in the opposite direction
    params = {"reduce_only": True}
    close_position_order = await exchange.createOrder(symbol, type, side, amount, price, params)
    print(close_position_order)


# -------------------------------------------------------------------------------------------


async def main():
    await example_2()


run(main())
