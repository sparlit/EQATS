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


# Python
from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
from pprint import pprint


async def place_delayed_order(exchange, symbol, amount, price):
    try:
        await exchange.sleep(5000)  # wait a bit
        await exchange.create_limit_buy_order(symbol, amount, price)
        print(exchange.iso8601(exchange.milliseconds()), "place_delayed_order")
        print("---------------------------------------------------------------")
    except Exception as e:
        # break
        print(e)


async def watch_orders_loop(exchange, symbol):
    while True:
        try:
            orders = await exchange.watch_orders(symbol)
            print(exchange.iso8601(exchange.milliseconds()), "watch_orders_loop", len(orders), " last orders cached")
            print("---------------------------------------------------------------")
        except Exception as e:
            # break
            print(e)


async def watch_balance_loop(exchange):
    while True:
        try:
            await exchange.watch_balance()
            print(exchange.iso8601(exchange.milliseconds()), "watch_balance_loop")
            print("---------------------------------------------------------------")
        except Exception as e:
            # break
            print(e)


async def main():
    exchange = ccxt.pro.binanceusdm(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
        }
    )
    symbol = "BTC/USDT"
    amount = 0.001
    price = 11111
    loops = [
        watch_orders_loop(exchange, symbol),
        watch_balance_loop(exchange),
        place_delayed_order(exchange, symbol, amount, price),
    ]
    await gather(*loops)
    await exchange.close()


run(main())
