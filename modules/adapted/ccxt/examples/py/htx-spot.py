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

exchange = ccxt.htx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "options": {
            "defaultType": "spot",
        },
    }
)

markets = exchange.load_markets()


# exchange.verbose = True  # uncomment for debugging purposes if necessary

# creating and canceling a stop-limit buy order
symbol = "ADA/USDT"
order_type = "limit"
side = "buy"
offset = "open"
amount = 10
price = 0.5
stopPrice = 0.6
operator = "lte"

params = {"offset": offset, "stopPrice": stopPrice, "operator": operator}

try:
    # Order creation
    order = exchange.create_order(symbol, order_type, side, amount, price, params)
    print(order)

    # List open positions
    open_orders = exchange.fetch_open_orders(symbol, params={"side": "buy"})
    print(open_orders)

    # Order cancelation
    cancelOrder = exchange.cancel_order(order["id"], symbol)
    print(cancelOrder)
except Exception as e:
    print(type(e).__name__, str(e))


# creating and canceling a stop limit sell order
symbol = "ADA/USDT"
order_type = "limit"
side = "sell"
offset = "open"
amount = 10
price = 5
stopPrice = 5
operator = "gte"

params = {"offset": offset, "stopPrice": stopPrice, "operator": operator}

try:
    # Order creation
    order = exchange.create_order(symbol, order_type, side, amount, price, params)
    print(order)

    # List open positions
    open_orders = exchange.fetch_open_orders(symbol, params={"side": "sell"})
    print(open_orders)

    # Order cancelation
    cancelOrder = exchange.cancel_order(order["id"], symbol)
    print(cancelOrder)
except Exception as e:
    print(type(e).__name__, str(e))
