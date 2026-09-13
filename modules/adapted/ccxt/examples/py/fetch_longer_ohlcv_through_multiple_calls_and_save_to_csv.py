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
from datetime import datetime

import ccxt  # noqa: E402
import numpy as np

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

print("CCXT Version:", ccxt.__version__)

# data
exchange_name = "okx"
symbol = "BTC/USD"
max_candles = 5000
timeframe = "1h"
start = 1609459200000  # Jan 1, 2021
ms_per_candle = {
    "1m": 60000,
    "5m": 300000,
    "15m": 900000,
    "30m": 1800000,
    "1h": 3600000,
    "2h": 7200000,
    "4h": 14400000,
    "8h": 28800000,
    "12h": 57600000,
    "1d": 86400000,
}

now = int(datetime.now().timestamp() * 1000)
outfile = f"{symbol.replace('/', '-')}_{timeframe}_{exchange_name}_{start}-{now}.csv"

# setup
exchange = ccxt.okx()
exchange.load_markets()
ohlcv = []

# make requests for candle data
while start < now:
    candles = exchange.fetch_ohlcv(symbol, timeframe, start, max_candles)
    ohlcv += candles
    start = start + (ms_per_candle[timeframe] * max_candles)

# write to csv
np.savetxt(outfile, ohlcv, delimiter=",", fmt="%d,%s,%s,%s,%s,%s")
