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
import psutil  # noqa: E402


def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process()
    memory_info = process.memory_info()
    return memory_info.rss / 1024 / 1024  # Convert to MB


async def test():
    print(f"Initial memory usage: {get_memory_usage():.2f} MB")

    binance = ccxt.binance({})
    print(f"Memory usage after creating binance: {get_memory_usage():.2f} MB")

    await binance.load_markets()
    print(f"Memory usage after loading markets: {get_memory_usage():.2f} MB")

    binance2 = ccxt.binance({})
    print(f"Memory usage after creating binance2: {get_memory_usage():.2f} MB")

    binance2.set_markets_from_exchange(binance)
    print(f"Memory usage after setting markets from exchange: {get_memory_usage():.2f} MB")
    print(f"binance2.symbols loaded: {len(binance2.symbols)}")

    await binance.close()
    await binance2.close()
    print(f"Final memory usage after closing: {get_memory_usage():.2f} MB")


run(test())
