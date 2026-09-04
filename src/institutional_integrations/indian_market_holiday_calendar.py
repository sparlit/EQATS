# codespell:ignore MIS,IST
"""
Indian Market Trading & Clearing Holiday Calendar Engine (EQATS Institutional Adaptation).
Adapted from adityazerodha/holiday-calendar.github.io into FOSS Microkernel Architecture.

Provides official NSE/BSE exchange trading holiday schedules, clearing holidays,
and special session rules (e.g. Diwali Muhurat Trading evening 1-hour session)
to safeguard automated order execution from invalid holiday order submissions.

Assigned Magic Number: 9100014
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger("IndianMarketHolidayCalendar")
MAGIC_NUMBER_HOLIDAY_CALENDAR = 9100014


class IndianMarketHolidayCalendar:
    """
    Official NSE/BSE Indian Exchange Holiday Calendar & Special Session Engine.
    """

    # Multi-year NSE/BSE Official Trading Holidays Registry (YYYY-MM-DD)
    NSE_TRADING_HOLIDAYS: Dict[str, str] = {
        # 2024
        "2024-01-22": "Special Holiday - Ram Mandir Pran Pratishtha",
        "2024-01-26": "Republic Day",
        "2024-03-08": "Mahashivratri",
        "2024-03-25": "Holi",
        "2024-03-29": "Good Friday",
        "2024-04-11": "Id-Ul-Fitr (Ramzan Id)",
        "2024-04-17": "Shri Ram Navami",
        "2024-05-01": "Maharashtra Day",
        "2024-05-20": "General Parliamentary Elections",
        "2024-06-17": "Bakri Id / Eid-ul-Adha",
        "2024-07-17": "Muharram",
        "2024-08-15": "Independence Day",
        "2024-10-02": "Mahatma Gandhi Jayanti",
        "2024-11-01": "Diwali Laxmi Pujan (Regular Trading Closed, Muhurat Session Active)",
        "2024-11-15": "Gurunanak Jayanti",
        "2024-12-25": "Christmas",
        # 2025
        "2025-01-26": "Republic Day",
        "2025-02-26": "Mahashivratri",
        "2025-03-14": "Holi",
        "2025-03-31": "Id-Ul-Fitr",
        "2025-04-10": "Shri Ram Navami",
        "2025-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
        "2025-04-18": "Good Friday",
        "2025-05-01": "Maharashtra Day",
        "2025-06-07": "Bakri Id",
        "2025-08-15": "Independence Day",
        "2025-08-27": "Ganesh Chaturthi",
        "2025-10-02": "Mahatma Gandhi Jayanti",
        "2025-10-21": "Diwali Laxmi Pujan",
        "2025-11-05": "Gurunanak Jayanti",
        "2025-12-25": "Christmas",
        # 2026
        "2026-01-26": "Republic Day",
        "2026-03-03": "Holi",
        "2026-04-03": "Good Friday",
        "2026-04-14": "Ambedkar Jayanti",
        "2026-05-01": "Maharashtra Day",
        "2026-08-15": "Independence Day",
        "2026-10-02": "Mahatma Gandhi Jayanti",
        "2026-11-08": "Diwali Laxmi Pujan",
        "2026-12-25": "Christmas",
    }

    # Special Diwali Muhurat Trading Dates (YYYY-MM-DD)
    MUHURAT_TRADING_DATES: Dict[str, str] = {
        "2024-11-01": "18:15 to 19:15 IST",
        "2025-10-21": "18:15 to 19:15 IST",
        "2026-11-08": "18:15 to 19:15 IST",
    }

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_HOLIDAY_CALENDAR

    def is_trading_holiday(self, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Checks if the given datetime/date is an official NSE/BSE trading holiday.
        Returns Tuple[is_holiday: bool, holiday_name: str].
        """
        target_date = (dt or datetime.now()).strftime("%Y-%m-%d")
        if target_date in self.NSE_TRADING_HOLIDAYS:
            return (True, self.NSE_TRADING_HOLIDAYS[target_date])
        return (False, "")

    def is_muhurat_trading_session(self, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Checks if the given date corresponds to special Diwali Muhurat trading.
        """
        target_date = (dt or datetime.now()).strftime("%Y-%m-%d")
        if target_date in self.MUHURAT_TRADING_DATES:
            return (True, f"Diwali Muhurat Trading Session ({self.MUHURAT_TRADING_DATES[target_date]})")
        return (False, "")

    def get_upcoming_holidays(self, limit: int = 5) -> List[Dict[str, str]]:
        """
        Returns list of upcoming NSE/BSE trading holidays from today onwards.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        upcoming = []
        for date_str, name in sorted(self.NSE_TRADING_HOLIDAYS.items()):
            if date_str >= today_str:
                upcoming.append({"date": date_str, "holiday_name": name})
                if len(upcoming) >= limit:
                    break
        return upcoming


global_indian_holiday_calendar = IndianMarketHolidayCalendar()
