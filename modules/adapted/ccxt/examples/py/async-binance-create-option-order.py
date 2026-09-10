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
# This example uses the implicit API, in the future we will have options unified which will make things easier.
# You can check if the unified methods are ready-to-use (createOrder, fetchOrder etc) by checking: `is_unified = exchange.has['option']`

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
    exchange = ccxt.binance(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            # 'verbose': True,  # for debug output
        }
    )
    await exchange.load_markets()
    symbol = "ETH/USDT:USDT-221028-1700-C"
    order_type = "limit"
    side = "buy"
    amount = 1
    price = 2.1
    try:
        await exchange.create_order(symbol, order_type, side, amount, price)
        # Implicit API:
        # response = await exchange.eapiPrivatePostOrder({
        #     # ETH/USDT call option strike 1700 USDT expiry on 2022-10-28
        #     'symbol': 'ETH-221028-1700-C',
        #     'side': 'BUY',
        #     'type': 'LIMIT',
        #     'quantity': 1,
        #     'price': 2.1,
        # })
    except ccxt.InsufficientFunds as e:
        print("create_order() failed - not enough funds")
        print(e)
    except Exception as e:
        print("create_order() failed")
        print(e)
    await exchange.close()


run(main())
