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


from datetime import date, timedelta

import holidays
import pandas as pd

"uncomment on every new year to fetch holiday csv from nse url"


def hol(root="path"):

    df_holidays = pd.read_csv(root + "indian_holidays.csv")

    df_holidays = df_holidays.set_index("date", drop=False)
    h_dict = df_holidays[["holiday"]].to_dict()

    custom_holidays = holidays.HolidayBase()

    custom_holidays.append(h_dict["holiday"])
    return custom_holidays


def check(dayback=0, root="path"):
    dt_1 = date.today() + timedelta(dayback)
    sday = dt_1.strftime("%Y-%m-%d")
    # mhol = check(sday)
    custom_holidays = hol(root)
    return sday in custom_holidays


def market_off(dayback=0, root="path"):

    mdate = date.today() + timedelta(dayback)
    msday = mdate.strftime("%A")
    sday = mdate.strftime("%Y-%m-%d")
    mhol = check(dayback, root)

    market_off = not (msday not in {"Saturday", "Sunday"} and not mhol)

    return (market_off, sday)


# my_week = market_off(dayback=-1,root='C:/Users/alex1/PycharmProjects/bhav/')
