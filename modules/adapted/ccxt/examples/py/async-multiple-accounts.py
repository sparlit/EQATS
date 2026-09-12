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

import asyncio
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt.async_support as ccxt  # noqa: E402


async def fetch_balance_n_times(code, account, n):
    exchange_class = getattr(ccxt, account["exchange_id"])
    exchange = exchange_class(account["params"])
    for _i in range(n):
        balance = await exchange.fetch_balance()
        print(exchange.id, code, "balance:", balance[code])
    await exchange.close()


async def test():
    n = 10  # fetch 10 times
    code = "BTC"
    accounts = [
        {
            "exchange_id": "binance",
            "params": {"id": "Binance1", "apiKey": "YOUR_API_KEY_1", "secret": "YOUR_API_SECRET_1"},
        },
        {
            "exchange_id": "binance",
            "params": {"id": "Binance2", "apiKey": "YOUR_API_KEY_2", "secret": "YOUR_API_SECRET_2"},
        },
    ]
    coroutines = [fetch_balance_n_times(code, account, n) for account in accounts]
    await asyncio.gather(*coroutines)


if __name__ == "__main__":
    run(test())
