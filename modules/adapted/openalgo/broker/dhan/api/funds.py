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


# api/funds.py

import json
import os

from broker.dhan.api.baseurl import get_url
from broker.dhan.api.order_api import get_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def test_auth_token(auth_token):
    """Test if the auth token is valid by making a simple API call to funds endpoint."""
    os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        url = get_url("/v2/fundlimit")
        res = client.get(url, headers=headers)
        res.status = res.status_code
        response_data = json.loads(res.text)

        # Check for authentication errors
        if response_data.get("errorType") == "Invalid_Authentication":
            error_msg = response_data.get("errorMessage", "Invalid authentication token")
            return False, error_msg

        # Check for other error types
        if response_data.get("status") == "error":
            error_msg = response_data.get("errors", "Unknown error occurred")
            return False, str(error_msg)

        # If we get here, authentication is valid
        return True, None

    except Exception as e:
        logger.error(f"Error testing auth token: {str(e)}")
        return False, f"Error validating authentication: {str(e)}"


def get_margin_data(auth_token):
    """Fetch margin data from Dhan API using the provided auth token."""
    os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = get_url("/v2/fundlimit")
    res = client.get(url, headers=headers)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    margin_data = json.loads(res.text)

    logger.info(f"Funds Details: {margin_data}")

    # Check for authentication errors first
    if margin_data.get("errorType") == "Invalid_Authentication":
        logger.error(f"Authentication error: {margin_data.get('errorMessage')}")
        return {
            "availablecash": "0.00",
            "collateral": "0.00",
            "m2munrealized": "0.00",
            "m2mrealized": "0.00",
            "utiliseddebits": "0.00",
        }

    if margin_data.get("status") == "error":
        # Log the error or return an empty dictionary to indicate failure
        logger.error(f"Error fetching margin data: {margin_data.get('errors')}")
        return {
            "availablecash": "0.00",
            "collateral": "0.00",
            "m2munrealized": "0.00",
            "m2mrealized": "0.00",
            "utiliseddebits": "0.00",
        }

    try:
        position_book = get_positions(auth_token)

        logger.info(f"Positionbook: {position_book}")

        # Check if position_book is an error response
        if isinstance(position_book, dict) and position_book.get("errorType"):
            logger.error(
                f"Error getting positions: {position_book.get('errorMessage', 'Unknown error')}"
            )
            total_realised = 0
            total_unrealised = 0
        else:
            # If successful, process the positions
            # position_book = map_position_data(position_book)

            def sum_realised_unrealised(position_book):
                total_realised = 0
                total_unrealised = 0
                if isinstance(position_book, list):
                    total_realised = sum(
                        position.get("realizedProfit", 0) for position in position_book
                    )
                    total_unrealised = sum(
                        position.get("unrealizedProfit", 0) for position in position_book
                    )
                return total_realised, total_unrealised

            total_realised, total_unrealised = sum_realised_unrealised(position_book)

        # Dhan's "availabelBalance" (their spelling) includes pledged
        # collateral, confirmed against a live account -- double-counting
        # against the separately reported "collateral" field below, same
        # class of bug as GitHub issue #1582. Subtract collateralAmount to
        # get the actual cash-only balance.
        available_cash = (margin_data.get("availabelBalance") or 0) - (
            margin_data.get("collateralAmount") or 0
        )

        # Construct and return the processed margin data with null checks
        processed_margin_data = {
            "availablecash": f"{available_cash:.2f}",
            "collateral": "{:.2f}".format(margin_data.get("collateralAmount") or 0),
            "m2munrealized": f"{total_unrealised or 0:.2f}",
            "m2mrealized": f"{total_realised or 0:.2f}",
            "utiliseddebits": "{:.2f}".format(margin_data.get("utilizedAmount") or 0),
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
