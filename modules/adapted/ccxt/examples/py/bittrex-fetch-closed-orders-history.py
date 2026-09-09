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


def table(values):
    first = values[0]
    keys = list(first.keys()) if isinstance(first, dict) else range(len(first))
    widths = [max([len(str(v[k])) for v in values]) for k in keys]
    string = " | ".join(["{:<" + str(w) + "}" for w in widths])
    return "\n".join([string.format(*[str(v[k]) for k in keys]) for v in values])


exchange = ccxt.kucoin(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
    }
)

exchange.load_markets()

symbol = "ETH/BTC"
market = exchange.markets[symbol]
starting_date = "2017-01-01T00:00:00"
now = exchange.milliseconds()

print("\nFetching history for:", symbol, "\n")

all_orders = []
since = exchange.parse8601(starting_date)

while since < now:
    try:
        print("Fetching history for", symbol, "since", exchange.iso8601(since))
        orders = exchange.fetch_closed_orders(symbol, since)
        print("Fetched", len(orders), "orders")

        all_orders = all_orders + orders

        if len(orders):
            last_order = orders[-1]
            since = last_order["timestamp"] + 1

        else:
            break  # no more orders left for this symbol, move to next one

    except Exception as e:
        print(e)


# omit the following keys for a compact table output
# otherwise it won't fit into the screen width
omitted_keys = [
    "info",
    "timestamp",
    "lastTradeTimestamp",
    "fee",
]

print(table([exchange.omit(order, omitted_keys) for order in all_orders]))
print("Fetched", len(all_orders), symbol, "orders in total")

# do whatever you want to do with them, calculate profit loss, etc...
