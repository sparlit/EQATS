import datetime
import pytz
import urllib.parse
import requests
import pandas as pd
import json
from typing import Optional, Dict, Any


def is_ist_market_session_active(dt: Optional[datetime.datetime] = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
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


def get_headers() -> Dict[str, str]:
    return {
        "Host": "www.nseindia.com",
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:85.0) Gecko/20100101 Firefox/85.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "X-Requested-With": "XMLHttpRequest",
        "DNT": "1",
        "Connection": "keep-alive",
    }


def get_cookies() -> Dict[str, str]:
    base_url = "https://www.nseindia.com/"
    response = requests.get(base_url, timeout=30, headers=get_headers())
    if response.status_code != requests.codes.ok:
        raise ValueError("Retry again in a minute.")
    return response.cookies.get_dict()


def fetch_url(url: str, cookies: Dict[str, str]) -> pd.DataFrame:
    response = requests.get(url, timeout=30, headers=get_headers(), cookies=cookies)
    if response.status_code == requests.codes.ok:
        json_response = json.loads(response.content)
        try:
            return pd.DataFrame.from_dict(json_response)
        except (ValueError, TypeError):
            return pd.DataFrame()
    return pd.DataFrame()


def get_corpinfo(
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    symbol: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetches corporate actions data for given date range and optional symbol.
    Args:
        start_date: start date
        end_date: end date
        symbol: stock symbol (optional)
    Returns:
        Pandas DataFrame containing corporate actions data
    """
    cookies = get_cookies()
    params = {
        "symbol": symbol or "",
        "from_date": start_date.strftime("%d-%m-%Y"),
        "to_date": end_date.strftime("%d-%m-%Y"),
        "index": "equities",
    }
    base_url = "https://www.nseindia.com/"
    equity_corpinfo = "api/corporates-corporateActions?"
    url = base_url + equity_corpinfo + urllib.parse.urlencode(params)
    return fetch_url(url, cookies)