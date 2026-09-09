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


from asyncio import ensure_future
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
from pprint import pprint

print("CCXT Version:", ccxt.__version__)


# on_connected() is called when a client connection is established
# note that the exchange will reuse the same client connection
# some exchanges might require two or more public/private connections
# therefore on_connected() may be called more than once


class MyBinance(ccxt.pro.binance):
    def on_connected(self, client, message=None):
        print("Connected to", client.url)
        ensure_future(create_order(self))


async def create_order(exchange):
    symbol = "BTC/USDT"
    type = "limit"
    side = "buy"
    amount = 123.45  # change for your values
    price = 54.321  # change for your values
    params = {}
    try:
        await exchange.create_order(symbol, type, side, amount, price, params)
        print("--------------------------------------------------------------")
        print("create_order():")
    except Exception as e:
        print(type(e).__name__, str(e))


async def watch_orders(exchange):
    while True:
        try:
            await exchange.watch_orders()
            print("--------------------------------------------------------------")
            print("watch_orders():")
        except Exception as e:
            print(type(e).__name__, str(e))
            break
    await exchange.close()


exchange = MyBinance(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
    }
)


run(watch_orders(exchange))
