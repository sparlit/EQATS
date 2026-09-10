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


data = {
    "orderbook": None,
    "balance": None,
}


def common_handler(exchange, symbol):
    market = exchange.market(symbol)
    market["base"]
    market["quote"]
    balance = data["balance"]
    orderbook = data["orderbook"]
    if balance and orderbook:
        total = balance["total"]
        tip = [orderbook["asks"][0], orderbook["bids"][0]]
        print(exchange.iso8601(exchange.milliseconds()), symbol, "orderbook:", tip, "balance:", total)


async def watch_order_book(exchange, symbol):
    while True:
        try:
            data["orderbook"] = await exchange.watch_order_book(symbol)
            common_handler(exchange, symbol)
        except Exception as e:
            print(type(e).__name__, str(e))
            break  # break this loop


async def watch_balance(exchange, symbol):
    while True:
        try:
            data["balance"] = await exchange.watch_balance()
            common_handler(exchange, symbol)
        except Exception as e:
            print(type(e).__name__, str(e))
            break  # break this loop


async def main():
    exchange = ccxt.pro.binance(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_SECRET",
        }
    )
    await exchange.load_markets()
    symbol = "BTC/USDT"
    while True:
        try:
            loops = [watch_order_book(exchange, symbol), watch_balance(exchange, symbol)]
            await gather(*loops)
        except Exception as e:
            print(type(e).__name__, str(e))
            break
    await exchange.close()


run(main())
