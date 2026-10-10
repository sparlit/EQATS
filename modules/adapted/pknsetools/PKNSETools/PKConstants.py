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
from PKDevTools.classes.Utils import random_user_agent

_base_domain = "https://www.nseindia.com"
_autoComplete_url_path = "/api/search/autocomplete?q={}"
_quote_url_path = "/api/quote-equity?symbol={}"
# Board meetings, corporate actions, financial results, latest announcements, shareholding patterns,
# https://www.nseindia.com/api/top-corp-info?symbol=SBIN&market=equities

# Bulk block deals, market dept order book/bid/ask, security wise DP
_quote_url_path_trade_info = f"{_quote_url_path}&section=trade_info&series=EQ"

# Equity meta data
# https://www.nseindia.com/api/equity-meta-info?symbol=SBIN
_daily_report_url_path = "/api/merged-daily-reports?key=favCapital"
_quote_url_path_html = "/get-quotes/equity?symbol={}"
_historical_company_data_url_path_html = "/api/historical/cm/equity?symbol={}"
_historical_company_data_url_path = (
    "/api/historical/cm/equity?symbol={}&series=[%22EQ%22]&from={}&to={}&csv=true"
)
_historical_index_data_url_path = "/api/historical/indicesHistory?indexType={}&from={}&to={}"
_chart_data_preopen_url = "/api/chart-databyindex?index={}&preopen=true"
_chart_data_open_url = "/api/chart-databyindex?index={}"
_chart_data_index_preopen_url = "/api/chart-databyindex?index={}&indices=true&preopen=true"
_chart_data_index_open_url = "/api/chart-databyindex?index={}&indices=true"
_headers = {"user-agent": random_user_agent()}
_head = {"user-agent": random_user_agent()}
