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

exchange = ccxt.htx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
        "options": {"defaultType": "swap", "marginType": "cross"},
    }
)

markets = exchange.load_markets()


exchange.verbose = True  # uncomment for debugging purposes if necessary


# Example: creating and closing a contract
symbol = "ADA/USDT:USDT"
order_type = "limit"  # market positions for contracts not available
side = "buy"
offset = "open"
leverage = 1
amount = 1
price = 1.14615  # adjust this accordingly
client_order_id = 1

params = {"offset": offset, "lever_rate": leverage, "client_order_id": client_order_id}

try:
    # fetching current balance
    balance = exchange.fetch_balance()
    # print(balance)

    # # placing an order
    order = exchange.create_order(symbol, order_type, side, amount, price, params)
    # print(order)

    # # list open position
    position = exchange.fetch_position(symbol)
    # print(position)

    # closing it by issuing an oposite contract
    # warning: since we can only place limit orders
    # it might take a while (depending on the price we choose and market fluctuations)
    # to the order be fulfilled
    # and therefore close our previous position
    side = "sell"
    type = "limit"
    offset = "close"
    reduce_only = 1  # 1 : yes, 0: no
    client_order_id = 5
    price = 1.11  # adjust this accordingly
    params = {"offset": offset, "reduce_only": reduce_only, "client_order_id": client_order_id}
    opositeOrder = exchange.create_order(symbol, order_type, side, amount, price, params)
    print(opositeOrder)
except Exception as e:
    print(type(e).__name__, str(e))
