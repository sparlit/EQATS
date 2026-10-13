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
import os

from broker.firstock.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate basket margin via Firstock's /V1/basketMargin endpoint.

    Applies MPP (Market Price Protection): MARKET/SL-M are converted to
    LMT/SL-LMT with a protected price before being sent, matching the
    place-order flow in broker/firstock/mapping/transform_data.py.
    """
    AUTH_TOKEN = auth

    api_key = os.getenv("BROKER_API_KEY")
    if not api_key:
        error_response = {
            "status": "error",
            "message": "BROKER_API_KEY not configured",
        }

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response

    # Firstock userId = BROKER_API_KEY with the "_API" suffix stripped,
    # matching the convention used in order_api.py and firstock_adapter.py.
    userid = api_key.replace("_API", "")

    margin_data = transform_margin_positions(positions, userid, auth_token=AUTH_TOKEN)

    if "tradingSymbol" not in margin_data:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Firstock V1 expects JSON body with jKey embedded (no Authorization header)
    margin_data["jKey"] = AUTH_TOKEN

    safe_payload = {k: v for k, v in margin_data.items() if k not in ("userId", "jKey")}
    logger.info(f"Firstock basket margin payload: {safe_payload}")

    client = get_httpx_client()
    headers = {"Content-Type": "application/json"}

    try:
        response = client.post(
            "https://api.firstock.in/V1/basketMargin",
            headers=headers,
            json=margin_data,
            timeout=30,
        )

        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text[:500]}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Firstock basket margin response: {response_data}")

        standardized_response = parse_margin_response(response_data)
        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Firstock basketMargin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
