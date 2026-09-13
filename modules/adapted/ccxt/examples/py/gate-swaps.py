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
from random import randint

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.gate(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
        "options": {
            "defaultType": "future",
        },
    }
)

markets = exchange.load_markets()

# exchange.verbose = True  # uncomment for debugging purposes if necessary

# Example 1: Creating and canceling a linear future (limit) order
symbol = "LTC/USDT:USDT"
type = "limit"
side = "buy"
amount = 1
price = 55

try:
    # placing an order
    order = exchange.create_order(symbol, type, side, amount, price)
    print(order)

    # listing open orders
    open_orders = exchange.fetch_open_orders(symbol)
    print(open_orders)

    # canceling an order
    cancelOrder = exchange.cancel_order(order["id"], symbol)
    print(cancelOrder)
except Exception as e:
    print(type(e).__name__, str(e))


# Example 2: Creating and canceling a linear future (stop-limit) order with leverage
symbol = "LTC/USDT:USDT"
type = "limit"
side = "buy"
amount = 1
price = 55
stop_price = 140
params = {"stopPrice": stop_price}

try:
    # set leverage
    leverage = exchange.set_leverage(3, symbol)
    print(leverage)

    # placing an order
    order = exchange.create_order(symbol, type, side, amount, price, params)
    print(order)

    # listing open orders
    open_orders = exchange.fetch_open_orders(symbol)
    print(open_orders)

    # canceling an order
    cancelParams = {"isStop": True}
    cancelOrder = exchange.cancel_order(order["id"], symbol, cancelParams)
    print(cancelOrder)

    # reset leverage
    exchange.set_leverage(1, symbol)
except Exception as e:
    print(type(e).__name__, str(e))
