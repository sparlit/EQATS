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

exchange = ccxt.poloniex()
exchange.load_markets()

symbol = "BTC/USDT"
timeframe = "5m"
since = exchange.parse8601("2024-01-01T00:00:00Z")
previous_length = 0
all_candles = []
limit = 500
duration = exchange.parse_timeframe(timeframe) * 1000
now = exchange.milliseconds()

while since < now:
    try:
        print("---------------------------------------------------------------")
        print("Fetching ohlcvs since", exchange.iso8601(since))
        endTime = since + duration * limit
        candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit, {"until": endTime})
        print("Fetched", len(candles), "candles")
        print("From", exchange.iso8601(candles[0][0]), "to", exchange.iso8601(candles[-1][0]))
        since = candles[-1][0] + duration
        all_candles += candles
        total_length = len(all_candles)
        print("Fetched", total_length, "candles in total")
    except ccxt.NetworkError as e:
        print(e)  # retry on next iteration
    except ccxt.ExchangeError as e:
        print(e)
        break

print(
    "Fetched",
    len(all_candles),
    "candles since",
    exchange.iso8601(all_candles[0][0]),
    "till",
    exchange.iso8601(all_candles[-1][0]),
)
