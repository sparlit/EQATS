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
from pprint import pprint

import ccxt.pro as ccxt

# This example will run silent and will return your balance only when the balance is updated.

# 1. launch the example with your keys and keep it running
# 2. go to the margin trading on the website
# 3. place a margin order on a spot market
# 4. see your balance updated in the example


async def main():
    exchange = ccxt.pro.binance(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            "options": {
                "defaultType": "margin",
            },
            # comment it out if you don't want debug output
            # this is for the demo purpose only (to show the communication)
            "verbose": True,
        }
    )
    while True:
        try:
            await exchange.watch_balance()
            # it will print the balance update when the balance changes
            # if the balance remains unchanged the exchange will not send it
        except Exception as e:
            print("watch_balance() failed")
            print(e)
            break
    await exchange.close()


run(main())
