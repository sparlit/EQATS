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
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")


import ccxt.async_support as ccxt


async def main():
    exchange = ccxt.bitget(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            "password": "YOUR_API_PASSWORD",
            "options": {
                "defaultType": "swap",
            },
        }
    )

    try:
        await exchange.load_markets()

        # exchange.verbose = True  # uncomment for debugging purposes if necessary

        # fetching balance
        balance = await exchange.fetch_balance()
        print(balance["total"])

        # placing a limit order
        symbol = "ETH/USDT:USDT"
        type = "limit"
        side = "buy"
        amount = 1  # how many contracts to buy or sell, integer number of contracts
        price = 3000
        order = await exchange.create_order(symbol, type, side, amount, price)
        print(order)

        # placing a market order
        symbol = "ETH/USDT:USDT"
        type = "market"
        side = "sell"
        amount = 1  # how many contracts to buy or sell, integer number of contracts
        order = await exchange.create_order(symbol, type, side, amount)
        print(order)

    except Exception as e:
        print(type(e).__name__, str(e))

    await exchange.close()


run(main())
