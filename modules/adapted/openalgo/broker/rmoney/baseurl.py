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


"""RMoney broker base URLs configuration."""

# HostLookup URL for RMoney XTS
HOSTLOOKUP_URL = "https://xts.rmoneyindia.co.in:4000/hostlookup"

# Base URL for RMoney XTS Interactive API endpoints
BASE_URL = "https://xts.rmoneyindia.co.in:3000"

# Base URL for RMoney XTS Market Data API (binary market data)
# Uses the same host but the market data API path is /apibinarymarketdata
MARKET_DATA_BASE_URL = BASE_URL

# Derived URLs for specific API endpoints
MARKET_DATA_URL = f"{MARKET_DATA_BASE_URL}/apibinarymarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
