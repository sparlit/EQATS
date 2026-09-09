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

import requests

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402

# configure the source IP address
ip_address = "192.168.1.2"  # YOUR EXTERNAL IP ADDRESS HERE
session = requests.Session()
for prefix in ("http://", "https://"):
    session.get_adapter(prefix).init_poolmanager(
        # those are default values from HTTPAdapter's constructor
        connections=requests.adapters.DEFAULT_POOLSIZE,
        maxsize=requests.adapters.DEFAULT_POOLSIZE,
        # This should be a tuple of (address, port). Port 0 means auto-selection.
        source_address=(ip_address, 0),
    )


exchange = ccxt.okx(
    {
        "session": session,
        # ... other config properties here if necessary ...
    }
)


markets = exchange.load_markets()
exchange.verbose = True

ticker = exchange.fetch_ticker("BTC/USD")
