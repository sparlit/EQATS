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


def style(s, style):
    return style + s + "\033[0m"


def green(s):
    return style(s, "\033[92m")


def blue(s):
    return style(s, "\033[94m")


def yellow(s):
    return style(s, "\033[93m")


def red(s):
    return style(s, "\033[91m")


def pink(s):
    return style(s, "\033[95m")


def bold(s):
    return style(s, "\033[1m")


def underline(s):
    return style(s, "\033[4m")


def log(*args):
    print(" ".join([str(arg) for arg in args]))


exchanges = {}

for id in ccxt.exchanges:
    exchange = getattr(ccxt, id)
    exchanges[id] = exchange()

log("The ccxt library supports", green(str(len(ccxt.exchanges))), "exchanges:")

# output a table of all exchanges
log(pink("{:<15} {:<15} {:<15}".format("id", "name", "URL")))
tuples = list(ccxt.Exchange.keysort(exchanges).items())
for id, _params in tuples:
    exchange = exchanges[id]
    website = exchange.urls["www"][0] if type(exchange.urls["www"]) is list else exchange.urls["www"]
    log(f"{exchange.id:<15} {exchange.name:<15} {website:<15}")
