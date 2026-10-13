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


import datetime
import json
import os

import requests

session = requests.session()  # session object..

week_expiry = next_week_expiry = month_expiry = None


def get_trading_holiday():
    year = datetime.datetime.now().year
    holiday = []

    if not os.path.isfile(f"holiday_{year}.json"):
        temp_file = open(f"holiday_{year}.json", "w")
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36"
        }
        res = session.get(
            "https://www.nseindia.com/api/holiday-master?type=trading", headers=headers
        )

        if res.status_code == 200:
            data = res.json()
            json.dump(data, temp_file, indent=4)

    temp_file = open(f"holiday_{year}.json")
    data = json.load(temp_file)
    for i in data["CM"]:
        holiday.append(datetime.datetime.strptime(i["tradingDate"], "%d-%b-%Y"))
    return holiday


def get_expiries():
    global expiries, week_expiry, next_week_expiry, month_expiry

    expiries = []
    today = today = datetime.datetime.now().date()
    start_expiry = today

    if today.weekday() == 4:
        start_expiry = today + datetime.timedelta(days=6)
    elif today.weekday() == 5:
        start_expiry = today + datetime.timedelta(days=5)
    elif today.weekday() == 6:
        start_expiry = today + datetime.timedelta(days=4)
    elif today.weekday() == 0:
        start_expiry = today + datetime.timedelta(days=3)
    elif today.weekday() == 1:
        start_expiry = today + datetime.timedelta(days=2)
    elif today.weekday() == 2:
        start_expiry = today + datetime.timedelta(days=1)
    else:
        start_expiry = today

    for i in range(12):
        expiries.append(start_expiry)
        start_expiry = start_expiry + datetime.timedelta(days=7)

    if expiries[0] < datetime.datetime.now().date():
        expiries.pop(0)

    for i in range(len(expiries)):
        if expiries[i] in holiday:
            expiries[i] = expiries[i] - datetime.timedelta(days=1)

    week_expiry = expiries[0]
    next_week_expiry = expiries[1]

    for i in range(1, len(expiries)):
        if (
            expiries[i].month != datetime.datetime.now().date().month
            and expiries[i - 1].month == datetime.datetime.now().date().month
        ):
            month_expiry = expiries[i - 1]
            break
    return expiries


holiday = get_trading_holiday()
expiries = get_expiries()
