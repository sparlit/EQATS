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


#!/usr/bin/env python
#
#  Copyright (c) 2007-2008, Corey Goldberg (corey@goldb.org)
#
#  license: GNU LGPL
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2.1 of the License, or (at your option) any later version.


import urllib

"""
This is the "ystockquote" module.

This module provides a Python API for retrieving stock data from Yahoo Finance.

sample usage:
>>> import ystockquote
>>> print ystockquote.get_price('GOOG')
529.46
"""


def __request(symbol, stat):
    url = f"http://finance.yahoo.com/d/quotes.csv?s={symbol}&f={stat}"
    return urllib.urlopen(url).read().strip().strip('"')


def get_all(symbol):
    """
    Get all available quote data for the given ticker symbol.

    Returns a dictionary.
    """
    values = __request(symbol, "l1c1va2xj1b4j4dyekjm3m4rr5p5p6s7").split(",")
    data = {}
    data["price"] = values[0]
    data["change"] = values[1]
    data["volume"] = values[2]
    data["avg_daily_volume"] = values[3]
    data["stock_exchange"] = values[4]
    data["market_cap"] = values[5]
    data["book_value"] = values[6]
    data["ebitda"] = values[7]
    data["dividend_per_share"] = values[8]
    data["dividend_yield"] = values[9]
    data["earnings_per_share"] = values[10]
    data["52_week_high"] = values[11]
    data["52_week_low"] = values[12]
    data["50day_moving_avg"] = values[13]
    data["200day_moving_avg"] = values[14]
    data["price_earnings_ratio"] = values[15]
    data["price_earnings_growth_ratio"] = values[16]
    data["price_sales_ratio"] = values[17]
    data["price_book_ratio"] = values[18]
    data["short_ratio"] = values[19]
    return data


def get_price(symbol):
    return __request(symbol, "l1")


def get_change(symbol):
    return __request(symbol, "c1")


def get_volume(symbol):
    return __request(symbol, "v")


def get_avg_daily_volume(symbol):
    return __request(symbol, "a2")


def get_stock_exchange(symbol):
    return __request(symbol, "x")


def get_market_cap(symbol):
    return __request(symbol, "j1")


def get_book_value(symbol):
    return __request(symbol, "b4")


def get_ebitda(symbol):
    return __request(symbol, "j4")


def get_dividend_per_share(symbol):
    return __request(symbol, "d")


def get_dividend_yield(symbol):
    return __request(symbol, "y")


def get_earnings_per_share(symbol):
    return __request(symbol, "e")


def get_52_week_high(symbol):
    return __request(symbol, "k")


def get_52_week_low(symbol):
    return __request(symbol, "j")


def get_50day_moving_avg(symbol):
    return __request(symbol, "m3")


def get_200day_moving_avg(symbol):
    return __request(symbol, "m4")


def get_price_earnings_ratio(symbol):
    return __request(symbol, "r")


def get_price_earnings_growth_ratio(symbol):
    return __request(symbol, "r5")


def get_price_sales_ratio(symbol):
    return __request(symbol, "p5")


def get_price_book_ratio(symbol):
    return __request(symbol, "p6")


def get_short_ratio(symbol):
    return __request(symbol, "s7")


def get_historical_prices(symbol, start_date, end_date):
    """
    Get historical prices for the given ticker symbol.
    Date format is 'YYYYMMDD'

    Returns a nested list.
    """
    url = (
        f"http://ichart.yahoo.com/table.csv?s={symbol}&"
        f"d={int(end_date[4:6]) - 1!s}&"
        f"e={int(end_date[6:8])!s}&"
        f"f={int(end_date[0:4])!s}&"
        "g=d&"
        f"a={int(start_date[4:6]) - 1!s}&"
        f"b={int(start_date[6:8])!s}&"
        f"c={int(start_date[0:4])!s}&"
        "ignore=.csv"
    )
    days = urllib.urlopen(url).readlines()
    return [day[:-2].split(",") for day in days]
