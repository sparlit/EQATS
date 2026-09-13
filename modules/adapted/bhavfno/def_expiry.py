import calendar
import datetime
from typing import List, Optional

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
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


def get_monthly_expiry_dates(year: int, holidays: list[datetime.date] | None = None) -> list[datetime.date]:
    """
    Returns list of monthly expiry dates (last Thursday of each month, adjusted for holidays).
    Index 0 is January, index 11 is December.
    """
    if holidays is None:
        holidays = []
    holiday_set = set(holidays)

    expiry_dates = []
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        # Find last Thursday (weekday 3)
        for day in range(last_day, 0, -1):
            candidate = datetime.date(year, month, day)
            if candidate.weekday() == 3:  # Thursday
                # Adjust for holidays: move to previous business day
                while candidate in holiday_set or candidate.weekday() >= 5:
                    candidate -= datetime.timedelta(days=1)
                expiry_dates.append(candidate)
                break
    return expiry_dates


def expiry(year: int, root: str = "path") -> list[str]:
    """
    Legacy wrapper for backward compatibility.
    Reads holidays from CSV and returns expiry dates as DD-MM-YYYY strings with dummy index 0.
    """
    try:
        import pandas as pd

        df_holidays = pd.read_csv(root + "indian_holidays.csv")
        df_holidays["date"] = pd.to_datetime(df_holidays["date"], format="%Y-%m-%d")
        holiday_list = df_holidays["date"].dt.date.tolist()
    except Exception:
        holiday_list = []

    expiry_dates = get_monthly_expiry_dates(year, holiday_list)
    # Format as DD-MM-YYYY strings with dummy "Empty" at index 0
    return ["Empty"] + [d.strftime("%d-%m-%Y") for d in expiry_dates]
