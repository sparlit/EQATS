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


"""Constants shared by more than one router or service.

Anything here is imported by at least two modules; single-use constants stay next to their
endpoint. Pulling these out is what keeps routers and services from importing each other.
"""
from zoneinfo import ZoneInfo

# The exchange's calendar, used wherever a timestamp has to be reduced to "which trading day was
# this" - price_history is keyed by plain date, so anything matching a timestamptz against it has
# to pick a timezone explicitly rather than let the server's locale decide.
IST = ZoneInfo("Asia/Kolkata")

# Manual-trade screenshot uploads - local disk only, matches the app's "nothing leaves your
# machine" design. Served straight back out at /uploads/<filename>.
UPLOAD_DIR = "uploads"

DIRECTIONS = {"long", "short"}
RESULTS = {"profit", "loss", "neutral"}
SUPPORTED_BROKERS = {"dhan", "kite"}
