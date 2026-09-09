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

exchange = ccxt.kraken(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
    }
)

exchange.load_markets()

# exchange.verbose = True  # uncomment for verbose debug output

exchange.rateLimit = 10000  # set a higher value if you get rate-limiting errors

all_trades = []
offset = 0
while True:
    trades = exchange.fetch_my_trades(symbol=None, since=None, limit=None, params={"ofs": offset})
    print("-----------------------------------------------------------------")
    print(exchange.iso8601(exchange.milliseconds()), "Fetched", len(trades), "trades")
    if len(trades) < 1:
        break
    else:
        first = exchange.safe_value(trades, 0)
        last = exchange.safe_value(trades, len(trades) - 1)
        print("From:", first["datetime"])
        print("To:", last["datetime"])
        all_trades = trades + all_trades
        offset += len(trades)
    print(len(all_trades), "trades fetched in total")

print("-----------------------------------------------------------------")
print(len(all_trades), "trades fetched")
first = exchange.safe_value(all_trades, 0)
if first:
    last = exchange.safe_value(all_trades, len(all_trades) - 1)
    print("First:", first["datetime"])
    print("Last:", last["datetime"])
