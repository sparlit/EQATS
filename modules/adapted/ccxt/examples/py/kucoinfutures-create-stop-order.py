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

# -----------------------------------------------------------------------------

print("CCXT Version:", ccxt.__version__)

# -----------------------------------------------------------------------------

exchange = ccxt.kucoinfutures(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "password": "YOUR_API_PASSWORD",
        # 'verbose': True,  # for debug output
    }
)

symbol = "BTC/USDT:USDT"
order_type = "limit"
side = "sell"
amount = 1
order_price = 13500  # below the stopLossPrice and above the takeProfitPrice
stop_trigger_params = {
    "triggerPrice": "14000",
    "leverage": 2,  # defaults to 1
}
# stop_loss_params = {
#     'stopLossPrice': '15000',  # the price that triggers the order_price order
#     'leverage': 1,
# }
# take_profit_params = {
#     'takeProfitPrice': '17000',  # the price that triggers the order_price order
#     'leverage': 1,
# }

try:
    stop_trigger_order = exchange.create_order(symbol, order_type, side, amount, order_price, stop_trigger_params)
    # stop_loss_order = exchange.create_order(symbol, order_type, side, amount, order_price, stop_loss_params)
    # take_profit_order = exchange.create_order(symbol, order_type, side, amount, order_price, take_profit_params)
    # pprint(stop_loss_order)
    # pprint(take_profit_order)
except Exception as err:
    print(err)
