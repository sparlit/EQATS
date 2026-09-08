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

import csv
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

exchange = ccxt.binance()

markets = exchange.load_markets()
symbol = "ETH/BTC"
market = exchange.market(symbol)
one_hour = 3600 * 1000
since = exchange.parse8601("2018-12-12T00:00:00")
now = exchange.milliseconds()
end = exchange.parse8601(exchange.ymd(now) + "T00:00:00")
previous_trade_id = None
filename = exchange.id + "_" + market["id"] + ".csv"
with open(filename, mode="w") as csv_f:
    csv_writer = csv.DictWriter(csv_f, delimiter=",", fieldnames=["timestamp", "size", "price", "side"])
    csv_writer.writeheader()
    while since < end:
        try:
            trades = exchange.fetch_trades(symbol, since)
            print(exchange.iso8601(since), len(trades), "trades")
            if len(trades):
                last_trade = trades[-1]
                if previous_trade_id != last_trade["id"]:
                    since = last_trade["timestamp"]
                    previous_trade_id = last_trade["id"]
                    for trade in trades:
                        csv_writer.writerow(
                            {
                                "timestamp": trade["timestamp"],
                                "size": trade["amount"],
                                "price": trade["price"],
                                "side": trade["side"],
                            }
                        )
                else:
                    since += one_hour
            else:
                since += one_hour
        except ccxt.NetworkError as e:
            print(type(e).__name__, str(e))
            exchange.sleep(60000)
