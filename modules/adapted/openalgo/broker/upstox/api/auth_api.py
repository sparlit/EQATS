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

import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code):
    try:
        BROKER_API_KEY = os.getenv("BROKER_API_KEY")
        BROKER_API_SECRET = os.getenv("BROKER_API_SECRET")
        REDIRECT_URL = os.getenv("REDIRECT_URL")

        if not all([BROKER_API_KEY, BROKER_API_SECRET, REDIRECT_URL]):
            logger.error(
                "Broker API key, secret, or redirect URL is not set in environment variables."
            )
            return None, "Configuration error: Missing API credentials."

        url = "https://api.upstox.com/v2/login/authorization/token"
        data = {
            "code": code,
            "client_id": BROKER_API_KEY,
            "client_secret": BROKER_API_SECRET,
            "redirect_uri": REDIRECT_URL,
            "grant_type": "authorization_code",
        }

        client = get_httpx_client()
        response = client.post(url, data=data)

        if response.status_code == 200:
            response_data = response.json()
            access_token = response_data.get("access_token")
            if access_token:
                logger.debug("Successfully authenticated with Upstox and received access token.")
                return access_token, None
            else:
                error_msg = "Authentication succeeded but no access token was returned."
                logger.error(f"{error_msg} Response: {response_data}")
                return None, error_msg
        else:
            error_msg = "Upstox API authentication failed."
            try:
                error_detail = response.json()
                errors = error_detail.get("errors", [])
                detailed_message = "; ".join(
                    [err.get("message", "Unknown error") for err in errors]
                )
                error_msg = f"Upstox API Error: {detailed_message}"
                logger.error(
                    f"{error_msg} | Status: {response.status_code}, Response: {response.text}"
                )
            except json.JSONDecodeError:
                logger.error(
                    f"{error_msg} | Status: {response.status_code}, Response: {response.text}"
                )
            return None, error_msg

    except httpx.RequestError as e:
        logger.exception("An HTTP request error occurred during Upstox authentication.")
        return None, f"An HTTP request error occurred: {e}"

    except Exception:
        logger.exception("An unexpected error occurred during Upstox authentication.")
        return None, "An unexpected error occurred during authentication."
