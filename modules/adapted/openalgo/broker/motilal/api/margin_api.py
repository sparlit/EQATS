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


"""Margin calculator for Motilal Oswal (MOFSL) — not offered by the broker.

Verified against the full API documentation set
(broker-api-docs/motilaloswal-api-docs/, 44 pages): there is no basket/order
margin calculator endpoint. The only margin endpoints are the reports
``/rest/report/v3/getreportmarginsummary`` (doc 24) and
``/rest/report/v3/getreportmargindetail`` (doc 25), which report the account's
current margin position and cannot price a hypothetical basket.

``services/margin_service.py`` converts the ``NotImplementedError`` raised here
into a clean ``501`` response, so raising is the supported way to decline.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions.

    Note: Motilal Oswal does not provide a margin calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Motilal Oswal

    Raises:
        NotImplementedError: Motilal Oswal does not support margin calculator API
            (handled as HTTP 501 by services/margin_service.py).
    """
    logger.warning("Motilal Oswal does not provide margin calculator API")
    raise NotImplementedError("Motilal Oswal does not support margin calculator API")
