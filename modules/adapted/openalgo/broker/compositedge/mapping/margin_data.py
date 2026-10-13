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


# Mapping OpenAlgo API Request https://openalgo.in/docs
# Compositedge does not provide Margin Calculator API

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to broker format.

    Note: Compositedge does not provide a margin calculator API.

    Args:
        positions: List of positions in OpenAlgo format

    Raises:
        NotImplementedError: Compositedge does not support margin calculator API
    """
    raise NotImplementedError("Compositedge does not support margin calculator API")


def parse_margin_response(response_data):
    """
    Parse broker margin calculator response to OpenAlgo standard format.

    Note: Compositedge does not provide a margin calculator API.

    Args:
        response_data: Raw response from broker margin calculator API

    Raises:
        NotImplementedError: Compositedge does not support margin calculator API
    """
    raise NotImplementedError("Compositedge does not support margin calculator API")
