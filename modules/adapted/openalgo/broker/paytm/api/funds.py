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


from broker.paytm.api.order_api import get_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Paytm API using the provided auth token."""
    try:
        base_url = "https://developer.paytmmoney.com"
        request_path = "/accounts/v1/funds/summary?config=true"
        headers = {
            "x-jwt-token": auth_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.debug(f"Making request to: {base_url}{request_path}")
        client = get_httpx_client()
        response = client.get(f"{base_url}{request_path}", headers=headers)
        margin_data = response.json()

        logger.debug(f"Funds Details: {margin_data}")

        if margin_data.get("status") == "error":
            error_details = margin_data.get("errors")
            logger.error(f"Error fetching margin data: {error_details}")
            logger.debug(f"Full error response from margin API: {margin_data}")
            return {}

        # Extracting funds summary safely
        funds_summary = margin_data.get("data", {}).get("funds_summary", {})
        position_book = get_positions(auth_token)
        logger.debug(f"Positionbook: {position_book}")

        def sum_realised_unrealised(position_book):
            total_realised = 0
            total_unrealised = 0
            if isinstance(position_book.get("data", []), list):
                for position in position_book["data"]:
                    total_realised += float(position.get("realised_profit", 0))
                    # Since all positions are closed, unrealized profit is 0
                    total_unrealised += float(position.get("unrealised_profit", 0))
            return total_realised, total_unrealised

        total_realised, total_unrealised = sum_realised_unrealised(position_book)

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{funds_summary.get('available_cash', 0):.2f}",
            "collateral": f"{funds_summary.get('collaterals', 0):.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{funds_summary.get('utilised_amount', 0):.2f}",
        }
        return processed_margin_data
    except Exception:
        logger.exception("An error occurred while fetching margin data")
        return {}
