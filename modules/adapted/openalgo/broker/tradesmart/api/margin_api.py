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


import json

from broker.tradesmart.api.baseurl import post, resolve_uid
from broker.tradesmart.mapping.margin_data import build_order_margin_payload, parse_order_margin
from utils.logging import get_logger

logger = get_logger(__name__)


class _MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def calculate_margin_api(positions, auth):
    """Calculate required margin for one or more positions.

    TradeSmart v2 only offers a single-order calculator (/GetOrderMargin), so we
    price each leg and sum the per-leg margins. Returns ``(response, data)`` with
    ``data.data = {total_margin_required, span_margin, exposure_margin}``.
    """
    if not positions:
        return _MockResponse(400), {"status": "error", "message": "No positions supplied"}

    total_margin = 0.0
    last_response = None
    priced_any = False
    uid = resolve_uid(auth)

    for position in positions:
        payload = build_order_margin_payload(position, uid=uid)
        if not payload:
            continue

        safe_payload = {k: v for k, v in payload.items() if k not in ("uid", "actid")}
        logger.info(f"TradeSmart order margin payload: {safe_payload}")

        try:
            response = post("/GetOrderMargin", payload, auth)
            last_response = response
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                logger.error(f"GetOrderMargin non-JSON response: {response.text}")
                return _MockResponse(502), {
                    "status": "error",
                    "message": "Invalid response from broker API",
                }

            logger.info(f"TradeSmart order margin response: {response_data}")

            leg_margin = parse_order_margin(response_data)
            if leg_margin is None:
                error_message = response_data.get("emsg") or "Failed to calculate margin"
                return _MockResponse(400), {"status": "error", "message": error_message}

            total_margin += leg_margin
            priced_any = True

        except Exception as e:
            logger.error(f"Error calling GetOrderMargin: {e}")
            return _MockResponse(500), {
                "status": "error",
                "message": f"Failed to calculate margin: {str(e)}",
            }

    if not priced_any:
        return _MockResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    response_obj = last_response if last_response is not None else _MockResponse(200)
    response_obj.status = getattr(response_obj, "status_code", 200)

    return response_obj, {
        "status": "success",
        "data": {
            "total_margin_required": total_margin,
            "span_margin": 0,
            "exposure_margin": 0,
        },
    }
