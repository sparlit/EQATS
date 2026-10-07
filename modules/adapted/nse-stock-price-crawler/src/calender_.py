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
import datetime

from dateutil.easter import *


class Calender:
    def __init__(self):
        calendar.setfirstweekday(calendar.MONDAY)
        self.calendar = calendar.Calendar()
        # add one day
        self._1daymore = datetime.timedelta(days=+1)
        # New Year's Day 1st January
        # Labour Day 1st May
        # Madaraka Day* 1st June
        # Mashujaa Day* 20th October
        # Jamhuri (Independence) Day* 12th December
        # Christmas Day 25th December
        # Boxing Day 26th December
        self.publicHolidays = {1: ["01"], 5: ["01"], 6: ["01"], 10: ["20"], 12: ["12", "25", "26"]}

    # Returns days of that month
    def getDayInMonth(self, year, month):
        weekdays = []
        self.month = month
        self.year = year
        for date in self.calendar.itermonthdates(year, month):
            newDate = datetime.datetime.strptime(str(date), "%Y-%m-%d").strftime("%Y%m%d")
            weekday = self.isWeekday(newDate)
            if weekday and int(newDate[4:6]) == month:
                weekdays.append(newDate)
                self._strMonth = newDate[4:6]
        tradingDays = self.holiday(weekdays)
        return tradingDays

    # removes the weekends from the days of the month
    def isWeekday(self, date):
        day = calendar.weekday(int(date[0:4]), int(date[4:6]), int(date[6:8]))
        return day < 5

    # removes a monday from the list if the holiday is on a Sunday
    def isHolidayOnSunday(self, day):
        date = datetime.datetime.strptime(str(day), "%Y%m%d").strftime("%Y-%m-%d")
        splitDate = date.split("-")
        whichDay = calendar.weekday(int(splitDate[0]), int(splitDate[1]), int(splitDate[2]))
        if whichDay == 6:  # if Sunday
            newdate = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            newHoliday = newdate + self._1daymore
            newHolidayDate = datetime.datetime.strptime(str(newHoliday), "%Y-%m-%d").strftime(
                "%Y%m%d"
            )
            return newHolidayDate
        else:
            return day

    # removes the holidays from the days of the month
    def holiday(self, monthDays):
        easterDays = []
        if self.month in self.publicHolidays:
            days = self.publicHolidays.__getitem__(self.month)
            for day in days:
                newDate = str(self.year) + str(self._strMonth) + day
                newDay = self.isHolidayOnSunday(newDate)
                if newDay in monthDays:
                    monthDays.remove(newDay)
        # remove easter
        easterSunday = easter(self.year)
        # go back two days
        _2daysLess = datetime.timedelta(days=-2)
        goodFriday = easterSunday + _2daysLess
        easterMonday = easterSunday + self._1daymore
        easterDays.append(
            datetime.datetime.strptime(str(goodFriday), "%Y-%m-%d").strftime("%Y%m%d")
        )
        easterDays.append(
            datetime.datetime.strptime(str(easterMonday), "%Y-%m-%d").strftime("%Y%m%d")
        )
        for easterDay in easterDays:
            if easterDay in monthDays:
                monthDays.remove(easterDay)
        return monthDays
