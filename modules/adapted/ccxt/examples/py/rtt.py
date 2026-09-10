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

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

# WARNING!
# This example measures the round-trip time when placing orders with an exchange
# In order to measure the speed of requests it disables the rate-limiting
# Disabling the rate-limiter is required to do an accurate measurement
# If you keep running without a rate limiter for a long time the exchange will ban you
# In a live production system always use either the built-in rate limiter or make your own


def main():

    # the exchange instance has to be reused
    # do not recreate the exchange before each call!

    exchange = ccxt.binance(
        {
            "apiKey": "YOUR_API_KEY",
            "secret": "YOUR_API_SECRET",
            # 'uid': 'YOUR_UID',  # some exchanges require this
            # 'password': 'YOUR_API_PASSWORD',  # some exchanges require this
            # if you do not rate-limit your requests the exchange can ban you!
            "enableRateLimit": False,  # https://github.com/ccxt/ccxt/wiki/Manual#rate-limit
        }
    )

    exchange.load_markets()  # https://github.com/ccxt/ccxt/wiki/Manual#loading-markets

    # exchange.verbose = True  # uncomment for debugging purposes if needed

    symbol = "BTC/USDC"
    market = exchange.market(symbol)
    ticker = exchange.fetch_ticker(symbol)

    amount = market["limits"]["amount"]["min"]

    # we will place limit buy order at 3/4 of the price to make sure they're not triggered

    price = ticker["last"] * 0.8
    amount = round(market["limits"]["cost"]["min"] / price, 4)

    results = []

    for _i in range(10):
        started = exchange.milliseconds()
        order = exchange.create_order(symbol, "limit", "buy", amount, price)
        ended = exchange.milliseconds()
        elapsed = ended - started
        results.append(elapsed)
        exchange.cancel_order(order["id"], order["symbol"])

    rtt = int(sum(results) / len(results))
    print("Successfully tested 10 orders, the average round-trip time per order is", rtt, "milliseconds")


main()
