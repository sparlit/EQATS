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

import os
import sys
from pprint import pprint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402


def table(values):
    first = values[0]
    keys = list(first.keys()) if isinstance(first, dict) else range(len(first))
    widths = [max([len(str(v[k])) for v in values]) for k in keys]
    string = " | ".join(["{:<" + str(w) + "}" for w in widths])
    return "\n".join([string.format(*[str(v[k]) for k in keys]) for v in values])


symbol = "BTC/USDT"

exchange = ccxt.latoken(
    {
        # 'verbose': True,  # uncomment for debugging purposes
        # uncomment and change for your keys to enable private calls
        # 'apiKey': 'YOUR_API_KEY',
        # 'secret': 'YOUR_API_SECRET',
    }
)

exchange.load_markets()

print("-------------------------------------------------------------------")

print(exchange.id, "has:")

# public API

print("-------------------------------------------------------------------")

markets = exchange.markets.values()
print("Loaded", len(markets), exchange.id, "markets:")
print(table([exchange.omit(x, ["info", "limits", "precision"]) for x in markets]))

print("-------------------------------------------------------------------")

currencies = exchange.currencies.values()
print("Loaded", len(currencies), exchange.id, "currencies:")
print(table([exchange.omit(x, ["info", "limits"]) for x in currencies]))

print("-------------------------------------------------------------------")

time = exchange.fetch_time()
print("Exchange time:", exchange.iso8601(time))

print("-------------------------------------------------------------------")

ticker = exchange.fetch_ticker(symbol)

print("-------------------------------------------------------------------")

tickers = exchange.fetch_tickers()
tickers = tickers.values()
print(table([exchange.omit(x, ["info", "bid", "ask", "bidVolume", "askVolume", "timestamp"]) for x in tickers]))

print("-------------------------------------------------------------------")

orderbook = exchange.fetch_order_book(symbol)

print("-------------------------------------------------------------------")

trades = exchange.fetch_trades(symbol)
print(table([exchange.omit(x, ["info", "timestamp"]) for x in trades]))

print("-------------------------------------------------------------------")

# private API

if exchange.check_required_credentials(False):
    balance = exchange.fetch_balance()

    print("-------------------------------------------------------------------")

    order = exchange.create_order(symbol, "limit", "buy", 0.001, 10000)

    print("-------------------------------------------------------------------")

    open_orders = exchange.fetch_open_orders(symbol)
    print(table([exchange.omit(x, ["info", "timestamp"]) for x in open_orders]))

    print("-------------------------------------------------------------------")

    canceled = exchange.cancel_order(order["id"], order["symbol"])

    print("-------------------------------------------------------------------")

    closed_orders = exchange.fetch_closed_orders(symbol)
    print(table([exchange.omit(x, ["info", "timestamp"]) for x in closed_orders]))

    print("-------------------------------------------------------------------")

    canceled_orders = exchange.fetch_canceled_orders(symbol)
    print(table([exchange.omit(x, ["info", "timestamp"]) for x in canceled_orders]))

    print("-------------------------------------------------------------------")

    my_trades = exchange.fetch_my_trades(symbol)
    print(table([exchange.omit(x, ["info", "timestamp"]) for x in my_trades]))
