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
        # 'options': {'adjustForTimeDifference': True}
    }
)

symbol = "SCRT/BTC"
market = exchange.market(symbol)
amount = 26
price = 0.00002
stop_price = 0.000016
stop_limit_price = 0.000015

response = exchange.private_post_order_oco(
    {
        "symbol": market["id"],
        "side": "SELL",  # SELL, BUY
        "quantity": exchange.amount_to_precision(symbol, amount),
        "price": exchange.price_to_precision(symbol, price),
        "stopPrice": exchange.price_to_precision(symbol, stop_price),
        "stopLimitPrice": exchange.price_to_precision(
            symbol, stop_limit_price
        ),  # If provided, stopLimitTimeInForce is required
        "stopLimitTimeInForce": "GTC",  # GTC, FOK, IOC
        # 'listClientOrderId': exchange.uuid(),  # A unique Id for the entire orderList
        # 'limitClientOrderId': exchange.uuid(),  # A unique Id for the limit order
        # 'limitIcebergQty': exchangea.amount_to_precision(symbol, limit_iceberg_quantity),
        # 'stopClientOrderId': exchange.uuid()  # A unique Id for the stop loss/stop loss limit leg
        # 'stopIcebergQty': exchange.amount_to_precision(symbol, stop_iceberg_quantity),
        # 'newOrderRespType': 'ACK',  # ACK, RESULT, FULL
    }
)
print(response)
