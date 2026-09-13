import calendar
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


def expiry(year: int, holiday_list: list[str] | None = None) -> list[str]:
    """
    Calculate NSE/BSE monthly expiry dates (last Thursday of each month, adjusted for holidays).

    Args:
        year: Year for which to calculate expiries
        holiday_list: List of holiday dates in "DD-MM-YYYY" format. If None, uses empty list.

    Returns:
        List of expiry dates in "DD-MM-YYYY" format, with index 1 = January, etc.
    """
    if holiday_list is None:
        holiday_list = []

    expiry_list = ["Empty"]  # Index 0 unused, so expiry_list[1] = January

    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        day_month = calendar.weekday(year, month, last_day)  # 0=Monday, 3=Thursday
        week = [3, 4, 5, 6, 0, 1, 2]  # Thursday=3, Friday=4, etc.
        days = -1

        for i in week:
            days += 1
            if i == day_month:
                break

        date_thu = last_day - days
        month_str = str(month).zfill(2)
        date_str = str(date_thu).zfill(2)
        expiry_date = f"{date_str}-{month_str}-{year}"

        # Check if last Thursday is a holiday, if so shift to Wednesday
        if expiry_date in holiday_list:
            date_wed = str(date_thu - 1).zfill(2)
            expiry_date = f"{date_wed}-{month_str}-{year}"

        expiry_list.append(expiry_date)

    return expiry_list
