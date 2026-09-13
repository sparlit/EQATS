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


from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run


print("CCXT Pro version", ccxt.pro.__version__)


async def watch_order_book(exchange, symbol):
    while True:
        try:
            orderbook = await exchange.watch_order_book(symbol)
            datetime = exchange.iso8601(exchange.milliseconds())
            print(datetime, orderbook["nonce"], symbol, orderbook["asks"][0], orderbook["bids"][0])
        except Exception as e:
            print(type(e).__name__, str(e))
            break


async def reload_markets(exchange, delay):
    while True:
        try:
            await exchange.sleep(delay)
            await exchange.load_markets(True)
            datetime = exchange.iso8601(exchange.milliseconds())
            print(datetime, "Markets reloaded")
        except Exception as e:
            print(type(e).__name__, str(e))
            break


async def main():
    exchange = ccxt.pro.binance()
    await exchange.load_markets()
    # exchange.verbose = True
    symbol = "BTC/USDT"
    delay = 60000  # every minute = 60 seconds = 60000 milliseconds
    loops = [watch_order_book(exchange, symbol), reload_markets(exchange, delay)]
    await gather(*loops)
    await exchange.close()


run(main())
