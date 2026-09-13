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

import ccxt.async_support as ccxt

print("CCXT Version:", ccxt.__version__)


async def main():
    exchange = ccxt.bitstamp(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
            "uid": "YOUR_UID",
        }
    )
    await exchange.load_markets()
    exchange.verbose = True  # enable verbose mode after loading the markets
    print("-------------------------------------------------------------------")
    try:
        await exchange.fetch_balance()
    except Exception as e:
        print("Failed to fetch the balance")
        print(type(e).__name__, str(e))
    order = None
    print("-------------------------------------------------------------------")
    try:
        symbol = "BTC/USDT"
        market = exchange.market(symbol)
        market["base"]
        market["quote"]
        amount = 0.001
        price = 40000
        order_type = "limit"
        side = "sell"
        order = await exchange.create_order(symbol, order_type, side, amount, price)
    except Exception as e:
        print("Failed to place", symbol, "order")
        print(type(e).__name__, str(e))
    print("-------------------------------------------------------------------")
    if order is not None:
        try:
            await exchange.cancel_order(order["id"], order["symbol"])
        except Exception as e:
            print("Failed to cancel", symbol, "order")
            print(type(e).__name__, str(e))
    print("-------------------------------------------------------------------")
    await exchange.close()


run(main())
