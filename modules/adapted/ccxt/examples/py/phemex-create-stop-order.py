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

exchange = ccxt.phemex(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
    }
)

# exchange.set_sandbox_mode(True)

# Example 1: Creating stop-market order
symbol = "LTC/USDT"
type = "market"
side = "buy"
amount = 0.5

params = {
    "stopPrice": 50,
}

stop_market = exchange.create_order(symbol, type, side, amount, None, params)
print(stop_market)

# Example 2: Create stop-limit order
symbol = "LTC/USDT"
type = "limit"
side = "buy"
amount = 0.5
price = 70

params = {
    "stopPrice": 50,
}

stop_limit = exchange.create_order(symbol, type, side, amount, price, params)
print(stop_limit)
