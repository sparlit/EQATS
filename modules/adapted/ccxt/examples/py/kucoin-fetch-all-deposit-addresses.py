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

exchange = ccxt.kucoin(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "password": "YOUR_API_PASSWORD",
    }
)

markets = exchange.load_markets()

exchange.verbose = True  # uncomment for debugging purposes if necessary

for code in ["TLOS"]:  # exchange.currencies.keys():
    response = exchange.public_get_currencies_currency({"currency": code})
    currency = exchange.safe_value(response, "data")
    if currency:
        # pprint(currency)
        chains = exchange.safe_value(currency, "chains")
        for chain in chains:
            chainName = exchange.safe_string(chain, "chainName")
            try:
                response = exchange.fetch_deposit_address(code, {"chain": chainName})
                if response["address"] is not None and response["address"] != "":
                    print(
                        code,
                        "has a",
                        chainName,
                        "address",
                        response["address"],
                        ":" + response["tag"] if response["tag"] is not None and len(response["tag"]) else "",
                    )
                else:
                    print(code, "has no", chainName, "address")
            except ccxt.BaseError:
                print(code, "has no", chainName, "address")
    else:
        print(code, "has no addresses")
