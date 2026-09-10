import concurrent
import datetime
import json
import urllib
from concurrent.futures import ALL_COMPLETED

import pytz
import requests

try:
    import pandas as pd
except ImportError:
    pd = None


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


HISTORICAL_DATA_URL = "https://www.nseindia.com/api/historical/cm/equity?series=[%22EQ%22]&"
BASE_URL = "https://www.nseindia.com/"


def get_adjusted_headers() -> dict:
    return {
        "priority": "u=0, i",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    }


def fetch_cookies() -> dict:
    response = requests.get(BASE_URL, timeout=30, headers=get_adjusted_headers())
    if response.status_code != requests.codes.ok:
        msg = "Please try again in a minute."
        raise ValueError(msg)
    return response.cookies.get_dict()


def fetch_url(url: str, cookies: dict) -> "pd.DataFrame":
    """
    This is the function call made by each thread. A get request is made for given start and end date, response is
    parsed and dataframe is returned
    """
    response = requests.get(url, timeout=30, headers=get_adjusted_headers(), cookies=cookies)
    if response.status_code == requests.codes.ok:
        json_response = json.loads(response.content)
        if pd is None:
            msg = "pandas is required for this function"
            raise ImportError(msg)
        return pd.DataFrame.from_dict(json_response["data"])
    msg = "Please try again in a minute."
    raise ValueError(msg)


def scrape_data(start_date: str, end_date: str, name: str | None = None, input_type: str = "stock") -> "pd.DataFrame":
    """
    Called by stocks and indices to scrape data.
    Create threads for different requests, parses data, combines them and returns data
    """
    if pd is None:
        msg = "pandas is required for this function"
        raise ImportError(msg)
    # Implementation would go here
    return pd.DataFrame()
