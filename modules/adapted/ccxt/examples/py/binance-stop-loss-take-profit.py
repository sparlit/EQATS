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

exchange = ccxt.binanceusdm(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
    }
)

markets = exchange.load_markets()
# exchange.verbose = True  # uncomment for debugging purposes

symbol = "BTC/USDT"
side = "buy"
amount = 0.01
price = None
stopLossPrice = 25000
takeProfitPrice = 35000

try:
    order = exchange.create_order(symbol, "MARKET", side, amount)
    print(order)

    inverted_side = "sell" if side == "buy" else "buy"

    stopLossParams = {"stopPrice": stopLossPrice}
    stopLossOrder = exchange.create_order(symbol, "STOP_MARKET", inverted_side, amount, price, stopLossParams)
    print(stopLossOrder)

    takeProfitParams = {"stopPrice": takeProfitPrice}
    takeProfitOrder = exchange.create_order(
        symbol, "TAKE_PROFIT_MARKET", inverted_side, amount, price, takeProfitParams
    )
    print(takeProfitOrder)

except Exception as e:
    print(type(e).__name__, str(e))
