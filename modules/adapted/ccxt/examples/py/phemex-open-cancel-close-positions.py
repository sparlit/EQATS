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

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.phemex(
    {
        "apiKey": "YOUR_API_KEY",  # testnet keys if using the testnet sandbox
        "secret": "YOUR_SECRET",  # testnet keys if using the testnet sandbox
        "options": {
            "defaultType": "swap",
        },
    }
)

# exchange.set_sandbox_mode(True)  # uncomment to use the testnet sandbox

markets = exchange.load_markets()

amount = 20
symbol = "BTC/USD:USD"

# Opening and Canceling a pending contract (limit) order
order = exchange.create_order(symbol, "limit", "buy", amount, "20000")
response = exchange.cancel_order(order["id"], symbol)

# Opening and Canceling a pending contract (stop-market) order
stopMarketOrder = exchange.create_order(
    symbol, "Stop", "buy", amount, None, {"stopPx": 70000}
)  # default triggerType is ByMarkPrice
stopMarketResponse = exchange.cancel_order(stopMarketOrder["id"], symbol)

# Opening and Canceling a pending contract (stop-limit) order
stopLimitOrder = exchange.create_order(
    symbol, "StopLimit", "buy", amount, 20000, {"stopPx": 70000, "triggerType": "ByLastPrice"}
)
stopLimitResponse = exchange.cancel_order(stopLimitOrder["id"], symbol)

# Opening and exiting a filled contract position by issuing the exact same order but in the opposite direction
order = exchange.create_order(symbol, "market", "buy", amount)
# closing the previous position by issuing the exact same order but in the opposite direction
# with reduceOnly option to prevent an unwanted exposure increase
orderClose = exchange.create_order(symbol, "market", "sell", amount, None, {"reduceOnly": True})

# Opening a contract position (market order) with TakeProfit and StopLoss prices defined
order = exchange.create_order(symbol, "market", "buy", amount, None, {"stopLossPrice": 5000, "takeProfitPrice": 100000})

# Opening a contract trailing (stop-limit) order
ethSymbol = "ETH/USD:USD"
ethPrice = 1000
stopPrice = 5000
trailingOrder = exchange.create_order(
    symbol=ethSymbol,
    type="StopLimit",
    side="buy",
    amount=1,
    price=ethPrice,
    params={
        "stopPrice": stopPrice,
        "ordType": "StopLimit",
        "pegPriceType": "TrailingStopPeg",
        "pegOffsetValueEp": 10000,  # needs to be scaled
    },  # default triggerType is ByMarkPrice
)
