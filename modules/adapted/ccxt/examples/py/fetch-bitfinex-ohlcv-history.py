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

# -----------------------------------------------------------------------------

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

# -----------------------------------------------------------------------------

import ccxt  # noqa: E402

# -----------------------------------------------------------------------------
# common constants

msec = 1000
minute = 60 * msec
hold = 30

# -----------------------------------------------------------------------------

exchange = ccxt.bitfinex()

# -----------------------------------------------------------------------------

from_datetime = "2017-01-01 00:00:00"
from_timestamp = exchange.parse8601(from_datetime)

# -----------------------------------------------------------------------------

now = exchange.milliseconds()

# -----------------------------------------------------------------------------

data = []

while from_timestamp < now:
    try:
        print(exchange.milliseconds(), "Fetching candles starting from", exchange.iso8601(from_timestamp))
        ohlcvs = exchange.fetch_ohlcv("BTC/USD", "5m", from_timestamp)
        print(exchange.milliseconds(), "Fetched", len(ohlcvs), "candles")
        if len(ohlcvs) > 0:
            first = ohlcvs[0][0]
            last = ohlcvs[-1][0]
            print("First candle epoch", first, exchange.iso8601(first))
            print("Last candle epoch", last, exchange.iso8601(last))
            # from_timestamp += len(ohlcvs) * minute * 5  # very bad
            from_timestamp = ohlcvs[-1][0] + minute * 5  # good
            data += ohlcvs

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print("Got an error", type(error).__name__, error.args, ", retrying in", hold, "seconds...")
        time.sleep(hold)
