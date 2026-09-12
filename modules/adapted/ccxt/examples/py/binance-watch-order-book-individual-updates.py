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
import ccxt.pro as ccxt


class MyBinance(ccxt.binance):
    def handle_order_book_message(self, client, message, orderbook):
        asks = self.safe_value(message, "a", [])
        bids = self.safe_value(message, "b", [])
        # printing high-frequency updates is a resource-heavy task
        # this print statement is here just to demonstrate the work of it
        # replace it with you logic for processing individual updates
        print(
            "Updates:",
            {
                "asks": asks,
                "bids": bids,
            },
        )
        return super().handle_order_book_message(client, message, orderbook)


async def main():
    exchange = MyBinance()
    symbol = "BTC/USDT"
    print("Watching", exchange.id, symbol)
    while True:
        try:
            await exchange.watch_order_book(symbol)
        except Exception as e:
            print(str(e))
            # raise e  # uncomment to break all loops in case of an error in any one of them
            # break  # you can also break just this one loop if it fails
    await exchange.close()


run(main())
