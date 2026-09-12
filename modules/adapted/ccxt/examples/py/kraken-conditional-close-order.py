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

from pprint import pprint

import ccxt  # noqa: E402

exchange = ccxt.kraken(
    {
        # 'apiKey': 'YOUR_API_KEY',
        # 'secret': 'YOUR_SECRET',
    }
)

markets = exchange.load_markets()

exchange.verbose = True

symbol = "XMR/USD"
ticker = exchange.fetch_ticker(symbol)
last_price = ticker["last"]

# extra params and overrides
params = {
    "close": {
        "ordertype": "limit",
        "price": last_price * 1.3,
    }
}
amount = 0.05
price = last_price * 0.7
order = exchange.create_order(symbol, "limit", "buy", amount, price, params)
print("Created order:")

fetched_order = exchange.fetch_order(order["id"])
print("Fetched order:")

canceled_order = exchange.cancel_order(order["id"])
print("Canceled order:")
