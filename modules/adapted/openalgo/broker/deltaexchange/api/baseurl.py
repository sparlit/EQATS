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


# Delta Exchange API Base URL Configuration
import hashlib
import hmac
import os
import time

# Base URL for Delta Exchange India REST API (Production).
# Override via DELTA_BASE_URL env var to point at the testnet.
BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")


def get_url(endpoint):
    """
    Constructs a full URL by combining the base URL and the endpoint.

    Args:
        endpoint (str): The API endpoint path (should start with '/')

    Returns:
        str: The complete URL
    """
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return BASE_URL + endpoint


def generate_signature(api_secret: str, message: str) -> str:
    """
    Generate HMAC-SHA256 signature for Delta Exchange API requests.

    Args:
        api_secret: The API secret key
        message: Prehash string: METHOD + timestamp + path + query_string + body

    Returns:
        Hex-encoded HMAC-SHA256 digest
    """
    return hmac.new(
        bytes(api_secret, "utf-8"),
        bytes(message, "utf-8"),
        hashlib.sha256,
    ).hexdigest()


def get_auth_headers(
    method: str,
    path: str,
    query_string: str = "",
    payload: str = "",
    api_key: str = None,
    api_secret: str = None,
) -> dict:
    """
    Build signed authentication headers for a Delta Exchange API request.

    Signature prehash: METHOD + timestamp + path + query_string + payload
    Note: query_string must include the leading '?' when present,
          e.g. '?product_id=27&state=open'

    Args:
        method:       HTTP method in uppercase (GET, POST, DELETE, ...)
        path:         Endpoint path, e.g. '/v2/orders'
        query_string: Raw query string including '?' prefix, or '' if none
        payload:      Request body as a JSON string, or '' for GET requests
        api_key:      API key override (falls back to BROKER_API_KEY env var)
        api_secret:   API secret override (falls back to BROKER_API_SECRET env var)

    Returns:
        dict of headers ready to pass to httpx / requests
    """
    key = api_key or os.getenv("BROKER_API_KEY", "")
    secret = api_secret or os.getenv("BROKER_API_SECRET", "")

    timestamp = str(int(time.time()))
    signature_data = method.upper() + timestamp + path + query_string + payload
    signature = generate_signature(secret, signature_data)

    return {
        "api-key": key,
        "timestamp": timestamp,
        "signature": signature,
        "User-Agent": "openalgo-python-client",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
