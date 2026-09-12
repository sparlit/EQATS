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
            "defaultType": "swap",
        },
    }
)

# exchange.set_sandbox_mode(True)

markets = exchange.load_markets()

exchange.verbose = True  # uncomment for debugging purposes if necessary


# Example: creating and closing a contract
symbol = "LTC/USDT:USDT"
order_type = "market"
side = "buy"
amount = 1

try:
    # fetching current balance
    balance = exchange.fetch_balance()
    # print(balance)

    # placing an order/ opening contract position
    order = exchange.create_order(symbol, order_type, side, amount)
    # print(order)

    # closing it by issuing an oposite contract
    # and therefore close our previous position
    side = "sell"
    type = "market"
    reduce_only = True
    params = {"reduce_only": reduce_only}
    opositeOrder = exchange.create_order(symbol, order_type, side, amount, None, params)
    print(opositeOrder)
except Exception as e:
    print(type(e).__name__, str(e))
