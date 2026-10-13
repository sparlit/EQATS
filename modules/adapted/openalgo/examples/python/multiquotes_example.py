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


import os

from openalgo import api

# Initialize client
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
)

# Fetch multiple quotes
response = client.multiquotes(
    symbols=[
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"},
        {"symbol": "INFY", "exchange": "NSE"},
    ]
)

print(response)
