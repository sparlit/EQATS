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


"""Static regression tests for credential-bearing broker log statements."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_LOG_PATTERNS = {
    "broker/fivepaisa/api/auth_api.py": (
        'f"The Request Token response is :{totp_data}"',
        'f"The Access Token response is :{token_data}"',
    ),
    "broker/mstock/api/auth_api.py": (
        'f"Using clientcode: {clientcode}"',
        'f"Available fields in data: {data}"',
        'f"Available fields in data: {final_data}"',
        "refresh_token[:30]",
        "dict(token_response.headers)",
        "token_response.text",
        'f"HTTP Error: {e.response.status_code}, Details: {error_detail}"',
        'f"HTTP Error: {e.response.status_code}, Raw: {e.response.text}"',
    ),
    "broker/mstock/api/funds.py": (
        'f"Full margin data response: {margin_data}"',
        'f"Response body: {e.response.text}"',
        'f"Error details: {error_detail}"',
    ),
    "broker/groww/api/funds.py": (
        'f"Getting margin data with token: {auth_token}..."',
        'f"Funds Details: {response_data}"',
    ),
    "broker/flattrade/api/auth_api.py": (
        'f"Request Data: {data}"',
        'f"Response Content: {response.text}"',
        'f"Exception: {e}"',
    ),
    "broker/dhan/api/auth_api.py": (
        'f"Generating consent for Dhan Client ID: {dhan_client_id}"',
        "BROKER_API_SECRET[:8]",
        'f"Consent generated successfully: {consent_app_id}"',
        'f"Additional Data: {additional_data}"',
        'f"Exception in generate_consent: {str(e)}"',
        'f"Exception in consume_consent: {str(e)}"',
        'f"Dhan authentication successful, client_id: {dhan_client_id}"',
        'f"Exception in authenticate_broker: {str(e)}"',
    ),
    "broker/paytm/api/auth_api.py": (
        'f"Token: {response_data}"',
        'f"Full response: {response_data}"',
    ),
    "broker/kotak/database/master_contract_db.py": (
        "access_token[:10]",
        'f"HTTP {response.status_code} from {base_url_attempt}: {response.text}"',
        'f"Response data: {data_dict}"',
        'f"Unexpected response structure from {base_url_attempt}: {data_dict}"',
        'f"Raw response: {response.text}"',
        'f"HTTP error with {base_url_attempt}: {e}"',
        'f"Error with {base_url_attempt}: {e}"',
    ),
}


def test_listed_broker_logs_do_not_include_credentials():
    """The issue's listed files must not reintroduce known secret dumps."""
    for relative_path, forbidden_patterns in FORBIDDEN_LOG_PATTERNS.items():
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{relative_path} contains {pattern!r}"
