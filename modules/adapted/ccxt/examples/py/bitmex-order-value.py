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

exchange = ccxt.bitmex()

markets = exchange.load_markets()
symbol = "XBTU20"
market = exchange.market(symbol)

units = {
    "XBT": {"decimals": 4, "multiplier": 1, "name": "bitcoin"},
    "mXBT": {"decimals": 3, "multiplier": 1000, "name": "milli-bitcoin"},
    "μXBT": {"decimals": 1, "multiplier": 1000000, "name": "micro-bitcoin"},
    "XBt": {"decimals": 0, "multiplier": 100000000, "name": "satoshi"},
}

# the following calculation depends on contract specifications
# one XBTU20 contract = 1 USD in Bitcoin

num_contracts = 1

while True:
    try:
        ticker = exchange.fetch_ticker(symbol)
        last_price = ticker["last"]
        value = num_contracts / last_price
        print("---------------------------------------------------------------")
        print(exchange.iso8601(exchange.milliseconds()))
        for unit in units:
            multiplier = units[unit]["multiplier"]
            decimals = units[unit]["decimals"]
            name = units[unit]["name"]
            rounded_value = exchange.decimal_to_precision(
                value * multiplier, ccxt.ROUND, decimals
            )  # alternatively, use ccxt.TRUNCATE here
            print(num_contracts, symbol, "contracts =", rounded_value, unit, "(" + name + ")")
    except Exception:
        pass
