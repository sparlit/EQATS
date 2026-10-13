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


# -*- coding: utf-8 -*-
from datetime import datetime

IST_TIMEZONE = "Asia/Kolkata"

__all__ = [
    "IST_time",
    "IST_date",
    "IST_datetime",
    "current_datetime_in_ist_trading_time_range",
    "datetime_in_ist_trading_time_range",
    "is_datetime_between",
    "is_trading_day",
    "trade_begin_datetime_ist",
    "trade_end_datetime_ist",
]


def IST_time():
    tz = pytz.timezone(IST_TIMEZONE)
    delhi_now = datetime.now(tz)
    return datetime.strptime(delhi_now.strftime("%H:%M:%S"), "%H:%M:%S").time()


def IST_date():
    tz = pytz.timezone(IST_TIMEZONE)
    delhi_now = datetime.now(tz)
    return datetime.strptime(delhi_now.strftime("%d-%m-%Y"), "%d-%m-%Y").date()


def IST_datetime():
    tz = pytz.timezone(IST_TIMEZONE)
    delhi_now = datetime.now(tz)
    return delhi_now


def is_trading_day():
    delhi_now = IST_datetime()
    return delhi_now.weekday() <= 4


def current_datetime_in_ist_trading_time_range():
    system_time = IST_datetime()
    trading_begin_time = trade_begin_datetime_ist()
    trading_end_time = trade_end_datetime_ist()
    return (
        is_datetime_between(trading_begin_time, trading_end_time, system_time) and is_trading_day()
    )


def datetime_in_ist_trading_time_range(check_datetime):
    trading_begin_time = trade_begin_datetime_ist()
    trading_end_time = trade_end_datetime_ist()
    return (
        is_datetime_between(trading_begin_time, trading_end_time, check_datetime)
        and is_trading_day()
    )


def is_datetime_between(begin_datetime, end_datetime, check_datetime=None):
    # If check datetime is not given, default to current IST datetime
    check_datetime = check_datetime or IST_datetime()
    if begin_datetime < end_datetime:
        return check_datetime >= begin_datetime and check_datetime <= end_datetime
    else:  # crosses midnight
        return check_datetime >= begin_datetime or check_datetime <= end_datetime


def trade_begin_datetime_ist():
    delhi_now = IST_datetime()
    tz = pytz.timezone(IST_TIMEZONE)
    begin_dt = datetime(delhi_now.year, delhi_now.month, delhi_now.day, 9, 15, tzinfo=tz)
    return begin_dt


def trade_end_datetime_ist():
    delhi_now = IST_datetime()
    tz = pytz.timezone(IST_TIMEZONE)
    end_dt = datetime(delhi_now.year, delhi_now.month, delhi_now.day, 15, 30, tzinfo=tz)
    return end_dt
