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

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

"""
Example snippet to traverse CoinBase Pro pagination.
Useful for reaching back more than 100 myTrades, the same works
for fetchClosedOrders
"""

exchange = ccxt.coinbasepro(
    {"apiKey": "123456", "secret": "/abcdefghijklmnop/w==", "password": "987654321", "enableRateLimit": True}
)

param_key = ""
param_value = ""
allMyTrades = []

while True:
    myTrades = exchange.fetch_my_trades(symbol="BTC/USD", params={param_key: param_value})

    # Handle with pagination ...
    if exchange.last_response_headers._store.get("cb-after"):
        param_key = "after"
        param_value = exchange.last_response_headers._store["cb-after"][1]

        allMyTrades.extend(myTrades)

    else:
        allMyTrades.extend(myTrades)
        break

for trade in allMyTrades:
    print(trade)
