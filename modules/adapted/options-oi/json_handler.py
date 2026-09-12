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

import json
import time

import requests

filename = "option_chain.json"


def get_OC_json(index_name):

    headers = {"User-Agent": "Mozilla/5.0"}

    #  when USD INR pair is added the word indices can be loaded as a conditional
    #  and be change to currency
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={index_name}"

    r = requests.get(url, headers=headers)

    content = r.json()

    with open(filename, "w") as json_file:
        json.dump(content, json_file, indent=4)

    #  The below sleep command will interfere with tkinter mainloop
    #  and will reflect as a button freeze
    #  alternative is to use tkinter action function with 5000 ms delay

    #  time.sleep(5)
    #  print(type(content))


def filter_OC_json_data():

    content = {}

    expiry_list = []
    strikes = []

    with open(filename) as json_file:
        content = json.load(json_file)

    # get strikes, Spot and ATM strike
    # underlying value is given as float in NIFTY,BANKNIFTY api
    # and as text in USDINR api

    spot = float(content["records"]["underlyingValue"])
    strikes = content["records"]["strikePrices"]
    expiry_list = content["records"]["expiryDates"]

    # print(spot)
    # print(type(content))

    return (spot, strikes, expiry_list)


# get_OC_json('NIFTY')
# filter_OC_json_data()
