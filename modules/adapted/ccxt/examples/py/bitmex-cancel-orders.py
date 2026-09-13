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

exchange = ccxt.bitmex(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_SECRET",
    }
)

# exchange.set_sandbox_mode(True)  # uncomment to use the testnet sandbox

symbol = "BTC/USD"
type = "limit"
side = "buy"
amount = 100
price = 15000

### Creating multiple orders and cancel them
### https://github.com/ccxt/ccxt/issues/10112

## Example 1
## Canceling orders using ClientOrderId

# create first order
order1 = exchange.create_order(symbol, type, side, amount, price, {"clientOrderId": "order0001"})
print(order1["id"])
# create second order
price = 10000
order2 = exchange.create_order(symbol, type, side, amount, price, {"clientOrderId": "order0002"})
print(order2["id"])
# create third order
price = 9000
order3 = exchange.create_order(symbol, type, side, amount, price, {"clientOrderId": "order0003"})
print(order3["id"])
# canceling first order
cancelResponse = exchange.cancel_order(None, None, {"clientOrderId": "order0001"})
print(cancelResponse)
# cancel second and third order at the same time
cancelboth = exchange.cancel_orders(None, None, {"clientOrderId": ["order0002", "order0003"]})
print(cancelboth)

## Example 2
## Canceling orders using OrderId

# create first order
newOrder1 = exchange.create_order(symbol, type, side, amount, price)
print(newOrder1["id"])
# create second order
price = 10000
newOrder2 = exchange.create_order(symbol, type, side, amount, price)
print(newOrder2["id"])
# create third order
price = 9000
newOrder3 = exchange.create_order(symbol, type, side, amount, price)
print(newOrder3["id"])
# canceling first order
cancelResponse = exchange.cancel_order(newOrder1["id"])
print(cancelResponse)
# cancel second and third order at the same time
ids = [newOrder2["id"], newOrder3["id"]]
cancelboth = exchange.cancel_orders(ids)
print(cancelboth)
