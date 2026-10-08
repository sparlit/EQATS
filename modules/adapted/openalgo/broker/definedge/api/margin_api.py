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

from broker.definedge.api.baseurl import get_url
from broker.definedge.api.rate_limiter import rate_limited_request
from broker.definedge.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Definedge API constants
DEFINEDGE_MARGIN_URL = get_url("/spancalculator")


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Definedge Span Calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token (format: api_session_key:::susertoken:::api_token)

    Returns:
        Tuple of (response, response_data)
    """
    # Parse the auth token
    try:
        api_session_key, susertoken, api_token = auth.split(":::")
    except ValueError:
        error_response = {
            "status": "error",
            "message": "Invalid auth token format. Expected format: api_session_key:::susertoken:::api_token",
        }

        class MockResponse:
            status_code = 401
            status = 401

        return MockResponse(), error_response

    # Transform positions to Definedge format
    transformed_positions = transform_margin_positions(positions)

    if not transformed_positions:
        error_response = {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

        class MockResponse:
            status_code = 400
            status = 400

        return MockResponse(), error_response

    # Prepare headers
    headers = {"Authorization": api_session_key, "Content-Type": "application/json"}

    # Prepare payload
    payload = {"positions": transformed_positions}

    logger.info(f"Definedge margin calculation payload: {json.dumps(payload, indent=2)}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    try:
        # Make the request to Definedge Span Calculator API
        response = rate_limited_request(
            client, "POST", DEFINEDGE_MARGIN_URL, headers=headers, json=payload
        )

        # Add status attribute for compatibility
        response.status = response.status_code

        # Parse the JSON response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response.text}")
            error_response = {"status": "error", "message": "Invalid response from broker API"}
            return response, error_response

        logger.info(f"Definedge margin calculation response: {json.dumps(response_data, indent=2)}")

        # Parse and standardize the response
        standardized_response = parse_margin_response(response_data)

        return response, standardized_response

    except Exception as e:
        logger.error(f"Error calling Definedge margin API: {e}")
        error_response = {"status": "error", "message": f"Failed to calculate margin: {str(e)}"}

        # Create a mock response object
        class MockResponse:
            status_code = 500
            status = 500

        return MockResponse(), error_response
