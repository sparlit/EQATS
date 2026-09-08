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

# make sure your version is the latest
print("CCXT Version:", ccxt.__version__)

exchange = ccxt.okx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "password": "YOUR_API_PASSWORD",
    }
)


markets = exchange.load_markets()

exchange.verbose = True  # uncomment for debugging

all_trades = {}
symbol = None
since = None
limit = 200
after = None

while True:
    print("------------------------------------------------------------------")
    params = {}
    if after:
        params["after"] = after
    trades = exchange.fetch_my_trades(symbol, since, limit, params)
    if len(trades):
        first_trade = trades[0]
        last_trade = trades[len(trades) - 1]
        after = first_trade["info"]["billId"]
        print("Fetched", len(trades), "trades from", first_trade["datetime"], "till", last_trade["datetime"])
        fetched_new_trades = False
        for trade in trades:
            trade_id = trade["id"]
            if trade_id not in all_trades:
                fetched_new_trades = True
                all_trades[trade_id] = trade
        if not fetched_new_trades:
            print("Done")
            break
    else:
        print("Done")
        break


all_trades = list(all_trades.values())
all_trades = exchange.sort_by(all_trades, "timestamp")

print("Fetched", len(all_trades), "trades")
for i in range(len(all_trades)):
    trade = all_trades[i]
    print(i, trade["id"], trade["datetime"], trade["amount"])
