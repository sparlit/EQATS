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

bitmex = ccxt.bitmex()

# fetch 5m OHLCV

symbol = "BTC/USD"

ohlcv5 = bitmex.fetch_ohlcv(symbol, "5m")
ohlcv15 = []

# OHLCV key indexes

timestamp = 0
open = 1
high = 2
low = 3
close = 4
volume = 5

# convert 5m → 15m

if len(ohlcv5) > 2:
    for i in range(0, len(ohlcv5) - 2, 3):
        highs = [ohlcv5[i + j][high] for j in range(3) if ohlcv5[i + j][high]]
        lows = [ohlcv5[i + j][low] for j in range(3) if ohlcv5[i + j][low]]
        volumes = [ohlcv5[i + j][volume] for j in range(3) if ohlcv5[i + j][volume]]
        candle = [
            ohlcv5[i + 0][timestamp],
            ohlcv5[i + 0][open],
            max(highs) if highs else None,
            min(lows) if lows else None,
            ohlcv5[i + 2][close],
            sum(volumes) if volumes else None,
        ]
        ohlcv15.append(candle)
else:
    msg = "Too few 5m candles"
    raise Exception(msg)

# do whatever you want with your 15m candles here...
