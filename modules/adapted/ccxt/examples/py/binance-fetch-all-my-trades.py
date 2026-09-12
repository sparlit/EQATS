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

exchange = ccxt.binance(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
        # 'options': {
        #     'defaultType': 'spot', // spot, future, margin
        # },
    }
)


exchange.load_markets()

# exchange.verbose = True  # uncomment for debugging

symbol = "BTC/USDT"
day = 24 * 60 * 60 * 1000
start_time = exchange.parse8601("2020-03-01T00:00:00")
now = exchange.milliseconds()

all_trades = []

while start_time < now:
    print("------------------------------------------------------------------")
    print("Fetching trades from", exchange.iso8601(start_time))
    end_time = start_time + day

    trades = exchange.fetch_my_trades(
        symbol,
        start_time,
        None,
        {
            "endTime": end_time,
        },
    )
    if len(trades):
        last_trade = trades[len(trades) - 1]
        start_time = last_trade["timestamp"] + 1
        all_trades = all_trades + trades
    else:
        start_time = end_time

print("Fetched", len(all_trades), "trades")
for i in range(len(all_trades)):
    trade = all_trades[i]
    print(i, trade["id"], trade["datetime"], trade["amount"])
