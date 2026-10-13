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


from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def get_margin_data(auth_token):
    """Fetch margin data from Samco's API using the provided auth token."""

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {"Accept": "application/json", "x-session-token": auth_token}

    response = client.get(f"{BASE_URL}/limit/getLimits", headers=headers)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    margin_data = response.json()

    logger.info(f"Samco Margin Data: {margin_data}")

    if margin_data.get("status") == "Success":
        equity_limit = margin_data.get("equityLimit", {})
        margin_data.get("commodityLimit", {})

        # Use equity segment as the primary margin source
        # Samco reports the same fund pool under both equity and commodity segments
        equity_available = float(equity_limit.get("netAvailableMargin", 0) or 0)
        equity_used = float(equity_limit.get("marginUsed", 0) or 0)

        # Map Samco fields to OpenAlgo standard format
        filtered_data = {
            "availablecash": f"{equity_available:.2f}",
            "collateral": "{:.2f}".format(
                float(equity_limit.get("collateralMarginAgainstShares", 0) or 0)
            ),
            "m2mrealized": f"{0:.2f}",  # Not provided by Samco
            "m2munrealized": f"{0:.2f}",  # Not provided by Samco
            "utiliseddebits": f"{equity_used:.2f}",
        }
        return filtered_data
    else:
        logger.error(
            f"Samco margin data fetch failed: {margin_data.get('statusMessage', 'Unknown error')}"
        )
        return {}
