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


import calendar

import pandas as pd


def expiry(year, root="path"):
    df_holidays = pd.read_csv(root + "indian_holidays.csv")
    df_holidays["date"] = pd.to_datetime(
        df_holidays["date"], format="%Y-%m-%d", infer_datetime_format=True
    ).dt.strftime("%d-%m-%Y")
    "Last Thu of the Month is a holiday. The list is manually created. Checked till 2015, if you want to add the support beyond 2015 then add the dates in 'holiday_list', also if possible share "
    holiday_list = df_holidays["date"].tolist()

    expiry_list = ["Empty"]  # since list starts from 0 this is a hacky way to align expiry_list[1] = first month
    for n in range(1, 13):
        month = n
        last_day = calendar.monthrange(year, month)[1]
        day_month = calendar.weekday(year, month, last_day)  # 0 is monday and 3 is Thu
        week = [3, 4, 5, 6, 0, 1, 2]
        days = -1

        for i in week:
            days += 1
            if i == day_month:
                break

        date_thu = last_day - days
        "zfill function formats single digits to double digits by adding a leading zero which is needed in NSE option url, comment it if not needed"
        month_1 = str(month).zfill(2)
        date_1 = str(date_thu).zfill(2)
        expiry = (date_1) + "-" + (month_1) + "-" + str(year)
        "check if last Thu of the month (expiry day) is not holiday, if it is holiday then shift the date by one to Wed"
        for h in holiday_list:
            if expiry == h:
                date2 = str(date_thu - 1).zfill(2)
                expiry = (date2) + "-" + (month_1) + "-" + str(year)
        # print(expiry)
        expiry_list.append(expiry)
    return expiry_list
