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


def dump(*args):
    print(" ".join([str(arg) for arg in args]))


# instantiate exchanges

coinbaseexchange = ccxt.coinbaseexchange(
    {
        "apiKey": "92560ffae9b8a01d012726c698bcb2f1",  # standard
        "secret": "9aHjPmW+EtRRKN/OiZGjXh8OxyThnDL4mMDre4Ghvn8wjMniAr5jdEZJLN/knW6FHeQyiz3dPIL5ytnF0Y6Xwg==",
        "password": "6kszf4aci8r",  # requires a password!
    }
)

coinbaseexchange.urls["api"] = coinbaseexchange.urls["test"]  # use the testnet

hitbtc = ccxt.hitbtc(
    {
        "apiKey": "18339694544745d9357f9e7c0f7c41bb",
        "secret": "8340a60fb4e9fc73a169c26c7a7926f5",
    }
)

try:
    # fetch account balance from the exchange
    coinbaseexchangeBalance = coinbaseexchange.fetch_balance()

    # output the result
    dump(green(coinbaseexchange.name), "balance", coinbaseexchangeBalance)

    # fetch another one
    hitbtcBalance = hitbtc.fetch_balance()

    # output the result
    dump(green(hitbtc.name), "balance", hitbtcBalance)

except ccxt.DDoSProtection as e:
    print(type(e).__name__, e.args, "DDoS Protection (ignoring)")
except ccxt.RequestTimeout as e:
    print(type(e).__name__, e.args, "Request Timeout (ignoring)")
except ccxt.ExchangeNotAvailable as e:
    print(type(e).__name__, e.args, "Exchange Not Available due to downtime or maintenance (ignoring)")
except ccxt.AuthenticationError as e:
    print(type(e).__name__, e.args, "Authentication Error (missing API keys, ignoring)")
