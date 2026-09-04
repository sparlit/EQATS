# codespell:ignore MIS,IST
"""
Unit Test Suite for adityazerodha/holiday-calendar.github.io Adaptation Module.
Verifies IndianMarketHolidayCalendar holiday checks, Diwali Muhurat Trading session detection,
and upcoming holiday retrieval.
"""

from datetime import datetime

from institutional_integrations.indian_market_holiday_calendar import (
    MAGIC_NUMBER_HOLIDAY_CALENDAR,
    IndianMarketHolidayCalendar,
    global_indian_holiday_calendar,
)


def test_indian_market_holiday_calendar_checks() -> None:
    cal = IndianMarketHolidayCalendar()

    # Republic Day 2024 (Jan 26)
    dt_republic_day = datetime(2024, 1, 26, 10, 0)
    is_hol, name = cal.is_trading_holiday(dt_republic_day)
    assert is_hol is True
    assert name == "Republic Day"

    # Regular Trading Day (Jan 25, 2024)
    dt_regular = datetime(2024, 1, 25, 10, 0)
    is_hol_reg, name_reg = cal.is_trading_holiday(dt_regular)
    assert is_hol_reg is False
    assert name_reg == ""

    # Diwali Muhurat Trading Session Check
    dt_diwali = datetime(2024, 11, 1, 18, 30)
    is_muhurat, desc = cal.is_muhurat_trading_session(dt_diwali)
    assert is_muhurat is True
    assert "Diwali Muhurat Trading" in desc

    upcoming = cal.get_upcoming_holidays(limit=3)
    assert isinstance(upcoming, list)
    assert cal.magic_number == MAGIC_NUMBER_HOLIDAY_CALENDAR
