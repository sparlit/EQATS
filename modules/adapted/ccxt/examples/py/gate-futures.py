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
        "secret": "YOUR_SECRET_KEY",
        "options": {
            "defaultType": "future",
        },
    }
)

markets = exchange.load_markets()

# exchange.verbose = True  # uncomment for debugging purposes if necessary

# Example 1: Creating a future (market) order
try:
    # find a valid future
    futures = []
    for key in markets:
        market = markets[key]
        if market["future"]:
            futures.append(market)

    if len(futures) > 0:
        market = futures[0]
        symbol = market["symbol"]  # example: BTC/USDT:USDT-220318
        type = "market"
        side = "buy"
        amount = 1

        # placing an order
        order = exchange.create_order(symbol, type, side, amount)
        print(order)

        # listing open orders
        open_orders = exchange.fetch_open_orders(symbol)
        print(open_orders)

except Exception as e:
    print(type(e).__name__, str(e))
