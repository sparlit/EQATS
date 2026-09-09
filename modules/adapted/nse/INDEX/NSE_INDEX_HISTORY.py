import datetime
import json

import pandas as pd
import pytz
import requests


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


BASE_URL = "https://www.niftyindices.com/"
HISTORICAL_DATA_URL = "https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString"


def get_adjusted_headers() -> dict:
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.niftyindices.com",
        "Referer": "https://www.niftyindices.com/reports/historical-data",
        "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    }


def fetch_cookies() -> dict:
    response = requests.get(BASE_URL, timeout=30, headers=get_adjusted_headers())
    if response.status_code != requests.codes.ok:
        msg = "Please try again in a minute."
        raise ValueError(msg)
    return response.cookies.get_dict()


def scrape_data(start_date: str, end_date: str, name: str, input_type: str = "index") -> pd.DataFrame:
    """
    Called by stocks and indices to scrape data.
    Create threads for different requests, parses data, combines them and returns dataframe
    Args:
        start_date (str): start date in format "%d-%m-%Y"
        end_date (str): end date in format "%d-%m-%Y"
        input_type (str): Either 'stock' or 'index'
        name (str): stock symbol or index name
    Returns:
        Pandas DataFrame: df containing data for stocksymbol for provided date range
    """
    cookies = fetch_cookies()

    start_dt = datetime.datetime.strptime(start_date, "%d-%m-%Y")
    end_dt = datetime.datetime.strptime(end_date, "%d-%m-%Y")

    pld = {
        "name": name,
        "startDate": start_dt.strftime("%d-%b-%Y"),
        "endDate": end_dt.strftime("%d-%b-%Y"),
        "indexName": name,
    }

    payload = {"cinfo": str(pld)}
    response = requests.request(
        "POST",
        HISTORICAL_DATA_URL,
        json=payload,
        timeout=30,
        headers=get_adjusted_headers(),
        cookies=cookies,
    )
    response.raise_for_status()
    data = response.json()
    return pd.DataFrame(data)