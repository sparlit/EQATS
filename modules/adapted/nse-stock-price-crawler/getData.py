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


import os
import shutil

from src import *

crawler = Crawler()
calender = Calender()
formatter = FormatData()

# start year
startYear = 2022
# start month
startMonth = 1
# end year
endYear = 2022
# end month
endMonth = 4

print("Preparing Daily Data")
while startYear < (endYear + 1):
    print("Year", startYear)
    while startMonth < 13:
        print("Month:", startMonth)
        month = calender.getDayInMonth(startYear, startMonth)
        for day in month:
            crawler.getURLData(int(day))
        if startMonth == endMonth and startYear == endYear:
            break
        startMonth += 1
    startMonth = 1
    startYear += 1


for folder in ["monthly", "yearly", "company"]:
    shutil.rmtree("data/" + folder, ignore_errors=True, onerror=None)
    os.mkdir("data/" + folder)


pathDaily = "data/daily/"
pathYearly = "data/yearly/"
pathMonthly = "data/monthly/"
pathCompany = "data/company/"

# create monthly data
print("Preparing Monthly Data")
formatter.getMonthlyData(pathDaily, pathMonthly)

# create yearly data
print("Preparing Yearly Data")
formatter.getYearlyData(pathMonthly, pathYearly)

# create company data
print("Preparing Company Data")
formatter.getCompanyData(pathYearly, pathCompany)

print("Process Completed !!")
