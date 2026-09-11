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
import ccxt.pro

print("CCXT Pro Version: ", ccxt.pro.__version__)

exchange = ccxt.pro.okx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "password": "YOUR_API_PASSWORD",
        "options": {"defaultType": "swap"},
    }
)


async def main():
    await exchange.load_markets()
    # exchange.verbose = True  # uncomment for debugging

    # https://github.com/ccxt/ccxt/wiki/Manual#overriding-unified-params
    # https://www.okx.com/docs/en/#swap-swap---orders

    symbol = "BTC/USDT:USDT"
    amount = 1  # how may contracts
    price = None  # or your limit price
    side = "buy"  # or 'sell'
    future_type = "1"  # 1 open long, 2 open short, 3 close long, 4 close short for futures

    try:
        # open long market price order
        order = await exchange.create_order(symbol, "market", side, amount, price, {"type": future_type})
        # --------------------------------------------------------------------
        # open long market price order
        # const order = await exchange.create_order(symbol, type, side, amount, price, {'order_type': order_type})
        # --------------------------------------------------------------------
        # close short market price order
        # const order = await exchange.create_order(symbol, 'market', side, amount, price, {'type': future_type, 'order_type': order_type})
        # --------------------------------------------------------------------
        # close short market price order
        # const order = await exchange.create_order(symbol, '4', side, amount, price, {'order_type': order_type})
        # ...
        print(order)
    except Exception as e:
        print(type(e).__name__, str(e))
    await exchange.close()


run(main())
