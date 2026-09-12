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

amount = 5
symbol = "BTC/USD:USD"

# Change leverage to the desired value
leverageResponse = exchange.set_leverage(5, symbol)

# Opening a pending contract (limit) order
order = exchange.create_order(symbol, "market", "buy", amount)
print(order)

# Canceling pending contract
closingOrder = exchange.create_order(symbol, "market", "sell", amount)

# Reset leverage to 1
leverageResponse = exchange.set_leverage(1, symbol)
print(leverageResponse)
