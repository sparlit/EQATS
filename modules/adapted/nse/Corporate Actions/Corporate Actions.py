
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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


# -*- coding: utf-8 -*-
"""### Import Dependencies"""

import urllib
import requests
import pandas as pd
import json

"""### Define Helper Functions """

def get_headers():
    return {
        "priority": "u=0, i",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    }
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

def get_corpinfo(start_date, end_date, symbol=None):
    """
    Create threads for different requests, parses data, combines them and returns dataframe
    Args:
        start_date (datetime.datetime): start date
        end_date (datetime.datetime): end date
        symbol (str, optional): stock symbol. Defaults to None. TODO: implement for index`
    Returns:
        Pandas DataFrame: df containing data for symbol of provided date range
    """
    cookies = get_cookies()
    params = {
        "symbol": symbol,
        "from_date": start_date,
        "to_date": end_date,
        "index": "equities",
    }
    # base_url = base_url
    base_url = "https://www.nseindia.com/"
    equity_corpinfo = "api/corporates-corporateActions?"
    price_api = equity_corpinfo
    url = base_url + price_api + urllib.parse.urlencode(params)
    return fetch_url(url, cookies)

def get_cookies():
    base_url = "https://www.nseindia.com/"
    response = requests.get(base_url, timeout=30, headers=get_headers())
    if response.status_code != requests.codes.ok:
        raise ValueError("Retry again in a minute.")
    return response.cookies.get_dict()


def fetch_url(url, cookies):
    response = requests.get(url, timeout=30, headers=get_headers(), cookies=cookies)
    if response.status_code == requests.codes.ok:
        json_response = json.loads(response.content)
        try:
            return pd.DataFrame.from_dict(json_response["data"])
        except:
            return pd.DataFrame.from_dict(json_response)
    else:
        raise ValueError("Please try again in a minute.")

"""### Scrape Directly to DataFrame """

start_date = "01-03-2020"
end_date = "26-05-2023"
print(get_corpinfo(start_date, end_date, symbol="TCS"))