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
import time

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

bitmex = ccxt.bitmex()

# params:
symbol = "BTC/USD"
timeframe = "1m"
limit = 100
params = {"partial": False}  # ←--------  no reversal

while True:
    # pay attention to since with respect to limit if you're doing it in a loop
    since = bitmex.milliseconds() - limit * 60 * 1000

    candles = bitmex.fetch_ohlcv(symbol, timeframe, since, limit, params)
    num_candles = len(candles)
    print(
        f"{bitmex.iso8601(candles[num_candles - 1][0])}: O: {candles[num_candles - 1][1]} H: {candles[num_candles - 1][2]} L:{candles[num_candles - 1][3]} C:{candles[num_candles - 1][4]}"
    )
    # * 5 to make distinct delay and to avoid too much load
    # / 1000 to convert milliseconds to fractional seconds
    time.sleep(bitmex.rateLimit * 5 / 1000)
