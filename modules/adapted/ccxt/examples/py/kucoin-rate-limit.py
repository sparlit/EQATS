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

print("CCXT Version:", ccxt.__version__)


exchange = ccxt.kucoin()
markets = exchange.load_markets()
i = 0
while True:
    try:
        symbol = "BTC/USDT"
        timeframe = "5m"
        since = None
        limit = 1000
        ohlcvs = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        now = exchange.milliseconds()
        datetime = exchange.iso8601(now)
        print(
            datetime,
            i,
            "fetched",
            len(ohlcvs),
            symbol,
            timeframe,
            "candles",
            "from",
            exchange.iso8601(ohlcvs[0][0]),
            "to",
            exchange.iso8601(ohlcvs[len(ohlcvs) - 1][0]),
        )
    except ccxt.RateLimitExceeded as e:
        now = exchange.milliseconds()
        datetime = exchange.iso8601(now)
        print(datetime, i, type(e).__name__, str(e))
        exchange.sleep(10000)
    except Exception as e:
        print(type(e).__name__, str(e))
        raise
    i += 1
