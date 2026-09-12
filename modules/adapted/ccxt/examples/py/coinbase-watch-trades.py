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

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run


async def main():
    exchange = ccxt.pro.coinbase()
    method = "watchTrades"
    print("CCXT Pro version", ccxt.pro.__version__)
    if exchange.has[method]:
        while True:
            try:
                trades = await exchange.watch_trades("BTC/USD")
                num_trades = len(trades)
                trade = trades[-1]
                print(
                    exchange.iso8601(exchange.milliseconds()),
                    trade["symbol"],
                    trade["datetime"],
                    trade["price"],
                    trade["amount"],
                    "stored",
                    num_trades,
                    "trades in cache",
                )
            except Exception:
                # stop
                await exchange.close()
                raise
                # or retry
                # pass
    else:
        raise Exception(exchange.id + " " + method + " is not supported or not implemented yet")


run(main())
