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

import pandas as pd

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

exchange = ccxt.poloniex()
exchange.load_markets()

# Poloniex will only serve one year of data into the past

symbol = "BTC/USDT"
before = exchange.milliseconds()
previous_length = 0
all_trades = {}

while True:
    try:
        print("---------------------------------------------------------------")
        print("Fetching trades before", exchange.iso8601(before))
        params = {
            "end": int(before / 1000)  # end param must be in seconds
        }
        trades = exchange.fetch_trades(symbol, None, None, params)
        trades_by_id = exchange.index_by(trades, "id")
        before = trades[0]["timestamp"]
        all_trades = exchange.extend(all_trades, trades_by_id)
        total_length = len(all_trades.keys())
        print("Fetched", total_length, "trades in total")
        if total_length == previous_length:
            break
        previous_length = total_length
    except ccxt.NetworkError as e:
        print(e)  # retry on next iteration
    except ccxt.ExchangeError as e:
        print(e)
        break

all_trades = exchange.sort_by(all_trades.values(), "id")
print("Fetched", len(all_trades), "trades since", all_trades[0]["datetime"], "till", all_trades[-1]["datetime"])

# omitted_keys = ['fee', 'info']
# all_trades = [exchange.omit(trade, omitted_keys) for trade in all_trades]
# path_to_your_csv_file = 'trades.csv'  # change for your path here
# df = pd.DataFrame(all_trades)
# df.to_csv(path_to_your_csv_file, index=None, header=True)
