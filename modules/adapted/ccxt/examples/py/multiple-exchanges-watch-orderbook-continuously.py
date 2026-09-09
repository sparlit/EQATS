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


import asyncio
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import time


async def watch_book(exchange, ticker):
    last = None
    while True:
        try:
            orderbook = await exchange.watch_order_book(ticker)
            top_bid = orderbook["bids"][0][0]
            if last != top_bid:
                print(f"{int(time.time() * 1000)} top bid for celo on {exchange.name} is {top_bid}")
            last = top_bid
        except Exception as e:
            print(f"{exchange.name} failed {type(e)} {e}")


async def main():
    exchange_ids = ["coinbaseexchange", "okcoin", "kucoin"]
    exchanges = [getattr(ccxt.pro, exchange_id)() for exchange_id in exchange_ids]
    try:
        done, _pending = await asyncio.wait(
            {watch_book(exchange, "CELO/USD") for exchange in exchanges}, return_when=asyncio.FIRST_EXCEPTION
        )
        for completed in done:
            # trigger the exception here
            completed.result()
    except Exception as e:
        print(f"closing all exchanges because of exception {type(e)} {e}")
        await asyncio.gather(*[exchange.close() for exchange in exchanges])


run(main())
