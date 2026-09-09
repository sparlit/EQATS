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


async def load(exchange, symbol, type="spot"):
    exchange.options["defaultType"] = type
    await exchange.load_markets(True)
    try:
        return {
            "balance": await exchange.fetch_balance(),
            # you actually want pagination here
            # https://github.com/ccxt/ccxt/wiki/Manual#pagination
            # but this will do as an example, tweak it for your needs
            "orders": await exchange.fetch_orders(symbol),
            "open orders": await exchange.fetch_open_orders(symbol),
            "closed orders": await exchange.fetch_closed_orders(symbol),
            "my trades": await exchange.fetch_my_trades(symbol),
        }
    except Exception as e:
        print("\n\nError in load() with type =", type, "-", e)
        raise


async def run():
    exchange = ccxt.binance(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
        }
    )
    symbol = "BTC/USDT"
    everything = {
        "spot": await load(exchange, symbol, "spot"),
        "future": await load(exchange, symbol, "future"),
    }
    await exchange.close()
    return everything


run(run())
