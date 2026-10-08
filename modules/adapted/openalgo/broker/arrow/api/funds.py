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


# broker/arrow/api/funds.py

from broker.arrow.api.baseurl import ROOT_URL, get_arrow_headers
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _to_float(value, default=0.0):
    """Arrow returns monetary values as strings; parse defensively."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_margin_data(auth_token):
    """Fetch funds/limits from Arrow and map to the OpenAlgo margin dict.

    Returns a dict with: availablecash, collateral, m2munrealized,
    m2mrealized, utiliseddebits. Returns {} on error.
    """
    client = get_httpx_client()
    headers = get_arrow_headers(auth_token)

    try:
        response = client.get(f"{ROOT_URL}/user/limits", headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_message = e.response.json().get("message", str(e))
        except Exception:
            pass
        logger.error(f"Error fetching Arrow margin data: {error_message}")
        return {}

    if payload.get("status") not in ("success", None):
        logger.error(f"Error fetching Arrow margin data: {payload.get('message')}")
        return {}

    try:
        data = payload.get("data", {})
        margin = data.get("margin", {}) or {}
        allocations = data.get("allocations", []) or []

        allocated = _to_float(margin.get("allocated"))
        utilized = _to_float(margin.get("utilized"))

        # Collateral = sum of non-cash component across all segments.
        # dedicated collateral field).
        collateral = sum(_to_float(a.get("nonCashCurrent")) for a in allocations)

        # utilized (free margin); alternative is the segment cashCurrent.
        available_cash = allocated - utilized

        processed = {
            "availablecash": f"{available_cash:.2f}",
            "collateral": f"{collateral:.2f}",
            "m2munrealized": f"{_to_float(margin.get('unrealizedPnl')):.2f}",
            "m2mrealized": f"{_to_float(margin.get('realizedPnl')):.2f}",
            "utiliseddebits": f"{utilized:.2f}",
        }
        return processed
    except (KeyError, AttributeError):
        return {}
