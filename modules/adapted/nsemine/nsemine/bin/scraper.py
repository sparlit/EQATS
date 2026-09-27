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


import time

import requests
from nsemine.bin import auth
from nsemine.utilities import urls

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
SESSION = requests.Session()


def _refresh_session_token() -> dict | None:
    """Fetches and stores a fresh NSE session token."""
    try:
        page_headers = urls.get_nse_headers(profile="page")

        response = SESSION.get(url=urls.first_boy, headers=page_headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        session_token = SESSION.cookies.get_dict()
        if session_token:
            auth.set_session_token(session_token)
            return session_token

    except Exception as e:
        print(f"Failed to refresh NSE session token: {e}")


def get_request(url: str, headers: dict | None = None, params: dict | None = None) -> requests.Response | None:
    """Sends an authenticated GET request to the NSE website."""
    try:
        if headers is None:
            headers = urls.get_nse_headers()

        session_token = auth.get_session_token()

        if session_token is None:
            session_token = _refresh_session_token()
            if not session_token:
                msg = "Failed to Connect to NSE."
                raise ValueError(msg)

        # sending api request to nse
        for retry_count in range(MAX_RETRIES):
            try:
                response = SESSION.get(
                    url=url, headers=headers, params=params, cookies=session_token, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                return response

            except requests.exceptions.Timeout as e:
                print(f"Request timed out ({retry_count + 1}/3): {e}")

            except requests.exceptions.ConnectionError as e:
                print(f"Connection error ({retry_count + 1}/3): {e}")

            except requests.exceptions.HTTPError as e:
                response = getattr(e, "response", None)
                status_code = response.status_code if response else None
                if status_code in (401, 403):
                    print(f"NSE session expired ({status_code}). Refreshing session token...")
                    try:
                        session_token = _refresh_session_token()
                        if session_token:
                            continue
                    except Exception as refresh_error:
                        print(f"Failed to refresh session token: {refresh_error}")
                print(f"HTTP error ({retry_count + 1}/3): {e}")

            except requests.exceptions.RequestException as e:
                print(f"Request error ({retry_count + 1}/3): {e}")

            # taking a short nap
            time.sleep((2**retry_count) + (time.time() % 1))

        print("Request failed after multiple retries.")
        return None

    except Exception as e:
        print(f"ERROR! - {e}\n")
        import traceback

        traceback.print_exc()
