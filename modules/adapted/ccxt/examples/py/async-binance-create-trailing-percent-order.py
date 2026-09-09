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
    exchange = ccxt.binanceusdm(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    try:
        # change the values here
        symbol = "BTC/USDT:USDT"
        type = "market"
        side = "sell"
        amount = 0.1
        price = None
        await exchange.create_order(
            symbol,
            type,
            side,
            amount,
            price,
            {
                "trailingPercent": 5,
                "reduceOnly": True,
                # 'trailingTriggerPrice': 45000,
            },
        )
        # Or you can call the create_trailing_percent_order method:
        # trailing_percent = 5
        # trailing_trigger_price = 45000
        # params = {
        #     'reduceOnly': True,
        # }
        # order = await exchange.create_trailing_percent_order (symbol, type, side, amount, price, trailing_percent, trailing_trigger_price, params)
    except ccxt.InsufficientFunds as e:
        print("create_order() failed - not enough funds")
        print(e)
    except Exception as e:
        print("create_order() failed")
        print(e)
    await exchange.close()


run(main())
