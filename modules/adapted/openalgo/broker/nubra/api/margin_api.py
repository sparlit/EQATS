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

from broker.nubra.api.baseurl import get_nubra_headers, get_url
from broker.nubra.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Nubra API.

    API: POST /sentinel/orders/funds_required

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (session_token) for Nubra

    Returns:
        Tuple of (response, response_data)
    """
    AUTH_TOKEN = auth

    # Transform positions to Nubra format (this returns the full payload)
    payload_data = transform_margin_positions(positions)

    if not payload_data:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        # Create a mock response object
        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Prepare headers
    headers = get_nubra_headers(AUTH_TOKEN)

    # Prepare JSON payload
    payload = json.dumps(payload_data)

    logger.info(f"Nubra margin calculation payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request using the shared client
        response = client.post(
            get_url("/sentinel/orders/funds_required"),
            headers=headers,
            content=payload,
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        # Log raw response for debugging
        logger.debug(f"Nubra margin raw response: {response.text}")

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Nubra margin calculation response: {response_data}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Nubra margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
