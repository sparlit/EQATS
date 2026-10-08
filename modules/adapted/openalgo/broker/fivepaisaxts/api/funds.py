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

import os

from broker.fivepaisaxts.baseurl import INTERACTIVE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Compositedge's API using the provided auth token."""
    os.getenv("BROKER_API_KEY")
    os.getenv("BROKER_API_SECRET")

    client = get_httpx_client()

    # conn = http.client.HTTPSConnection("xts.compositedge.com")

    headers = {"authorization": auth_token, "Content-Type": "application/json"}

    response = client.get(f"{INTERACTIVE_URL}/user/balance", headers=headers)

    margin_data = response.json()

    # logger.info(f"Funds Details: {margin_data}")

    if (
        margin_data.get("result")
        and margin_data["result"].get("BalanceList")
        and margin_data["result"]["BalanceList"]
    ):
        rms_sublimits = margin_data["result"]["BalanceList"][0]["limitObject"]["RMSSubLimits"]

        required_keys = [
            "netMarginAvailable",
            "collateral",
            "UnrealizedMTM",
            "RealizedMTM",
            "marginUtilized",
        ]

        filtered_data = {}
        for key in required_keys:
            value = rms_sublimits.get(key, 0)
            try:
                formatted_value = f"{float(value):.2f}" if str(value).lower() != "nan" else "0.00"
            except (ValueError, TypeError):
                formatted_value = "0.00"

            filtered_data[key] = formatted_value
            # logger.info(f"Funds Dashboard: {key} = {filtered_data[key]}")

        processed_margin_data = {
            "availablecash": filtered_data.get("netMarginAvailable"),
            "collateral": filtered_data.get("collateral"),
            "m2munrealized": filtered_data.get("UnrealizedMTM"),
            "m2mrealized": filtered_data.get("RealizedMTM"),
            "utiliseddebits": filtered_data.get("marginUtilized"),
        }

        # logger.info(f"Funds = {processed_margin_data}")
        return processed_margin_data
    else:
        return {}
