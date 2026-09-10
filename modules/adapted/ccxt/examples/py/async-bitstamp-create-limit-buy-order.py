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

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402


async def test():

    exchange = ccxt.bitstamp(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
        }
    )

    response = None

    try:
        await exchange.load_markets()  # force-preload markets first

        exchange.verbose = True  # this is for debugging

        symbol = "BTC/USD"  # change for your symbol
        amount = 1.0  # change the amount
        price = 6000.00  # change the price

        try:
            response = await exchange.create_limit_buy_order(symbol, amount, price)

        except Exception as e:
            print("Failed to create order with", exchange.id, type(e).__name__, str(e))

    except Exception as e:
        print("Failed to load markets from", exchange.id, type(e).__name__, str(e))

    await exchange.close()
    return response


print(run(test()))
