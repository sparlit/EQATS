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


async def main():
    exchange = ccxt.okx(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            # okx requires this: https://github.com/ccxt/ccxt/wiki/Manual#authentication
            "password": "YOUR_API_PASSWORD",
            # 'verbose': True,  # for debug output
        }
    )
    try:
        # change the values here
        symbol = "BTC/USDT"
        price = 123.45
        amount = 54.321
        type = "limit"  # or market
        side = "sell"
        await exchange.create_order(
            symbol,
            type,
            side,
            amount,
            price,
            {
                "margin": True,
                "marginMode": "cross",
            },
        )
    except ccxt.InsufficientFunds as e:
        print("create_order() failed – not enough funds")
        print(e)
    except Exception as e:
        print("create_order() failed")
        print(e)
    await exchange.close()


run(main())
