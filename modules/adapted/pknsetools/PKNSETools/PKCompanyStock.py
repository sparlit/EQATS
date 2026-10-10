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


#!/usr/bin/python3
"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""
import json
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests
from PKNSETools.PKConstants import (
    _base_domain,
    _head,
    _historical_company_data_url_path,
    _historical_company_data_url_path_html,
    _historical_index_data_url_path,
    _quote_url_path_html,
)

session = requests.session()


def get_Company_History_Data(company, from_date=None, to_date=None):
    if from_date is None:
        from_date = datetime.today().strftime("%d-%m-%Y")
    if to_date is None:
        to_date = datetime(
            datetime.today().year - 1, datetime.today().month, datetime.today().day
        ).strftime("%d-%m-%Y")
    session.get(f"{_base_domain}", headers=_head)
    session.get(
        f"{_base_domain}{_quote_url_path_html}".format(company), headers=_head
    )  # to save cookies
    session.get(
        f"{_base_domain}{_historical_company_data_url_path_html}".format(company), headers=_head
    )
    url = f"{_base_domain}{_historical_company_data_url_path}".format(company, from_date, to_date)
    webdata = session.get(url=url, headers=_head)
    df = pd.read_csv(StringIO(webdata.text[3:]))
    return df


def get_nifty_History_Data(indexName, from_date=None, to_date=None):
    if from_date is None:
        from_date = (
            datetime(datetime.today().year - 1, datetime.today().month, datetime.today().day)
            + timedelta(days=2)
        ).strftime("%d-%m-%Y")
    if to_date is None:
        to_date = datetime.today().strftime("%d-%m-%Y")
    indexName = indexName.upper()
    indexName = indexName.replace(" ", "%20")
    indexName = indexName.replace("-", "%20")
    session.get(f"{_base_domain}", headers=_head)
    webData = session.get(
        url=f"{_base_domain}{_historical_index_data_url_path}".format(
            indexName, from_date, to_date
        ),
        headers=_head,
    )
    indexData = webData.json()["data"]["indexCloseOnlineRecords"]
    data = pd.DataFrame(json.loads(str(line).replace("'", '"')) for line in indexData)
    return data
