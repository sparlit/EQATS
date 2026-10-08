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


# services/market_calendar_service.py
"""
Market Calendar Service
Handles business logic for market holidays and timings API
"""

from datetime import date, datetime
from typing import Any

from database.market_calendar_db import (
    SUPPORTED_EXCHANGES,
    get_holidays_by_year,
    get_market_timings_for_date,
    is_market_holiday,
)
from utils.logging import get_logger

logger = get_logger(__name__)

MIN_SUPPORTED_DATE = date(2020, 1, 1)
MAX_SUPPORTED_DATE = date(2050, 12, 31)


def _is_supported_date(query_date: date) -> bool:
    return MIN_SUPPORTED_DATE <= query_date <= MAX_SUPPORTED_DATE


def get_holidays(year: int | None = None) -> tuple[bool, dict[str, Any], int]:
    """
    Get market holidays for a specific year or current year

    Args:
        year: The year to get holidays for (defaults to current year)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Default to current year if not provided
        if year is None:
            year = datetime.now().year

        # Validate year
        if year < 2020 or year > 2050:
            return False, {"status": "error", "message": "Year must be between 2020 and 2050"}, 400

        logger.info(f"Fetching holidays for year: {year}")

        holidays = get_holidays_by_year(year)

        return (
            True,
            {"status": "success", "year": year, "timezone": "Asia/Kolkata", "data": holidays},
            200,
        )

    except Exception as e:
        logger.exception(f"Error fetching holidays: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred while fetching holidays"},
            500,
        )


def get_timings(date_str: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get market timings for a specific date

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Parse and validate date
        try:
            query_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return False, {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}, 400

        if not _is_supported_date(query_date):
            return (
                False,
                {"status": "error", "message": "Date must be between 2020-01-01 and 2050-12-31"},
                400,
            )

        logger.info(f"Fetching market timings for date: {date_str}")

        timings = get_market_timings_for_date(query_date)

        return True, {"status": "success", "data": timings}, 200

    except Exception as e:
        logger.exception(f"Error fetching market timings: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred while fetching market timings"},
            500,
        )


def check_holiday(date_str: str, exchange: str | None = None) -> tuple[bool, dict[str, Any], int]:
    """
    Check if a specific date is a market holiday

    Args:
        date_str: Date in YYYY-MM-DD format
        exchange: Optional exchange code to check

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Parse and validate date
        try:
            query_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return False, {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}, 400

        if not _is_supported_date(query_date):
            return (
                False,
                {"status": "error", "message": "Date must be between 2020-01-01 and 2050-12-31"},
                400,
            )

        # Validate exchange if provided
        if exchange and exchange.upper() not in SUPPORTED_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Exchange must be one of: {', '.join(SUPPORTED_EXCHANGES)}",
                },
                400,
            )

        is_holiday = is_market_holiday(query_date, exchange)

        return (
            True,
            {
                "status": "success",
                "data": {
                    "date": date_str,
                    "exchange": exchange.upper() if exchange else "ALL",
                    "is_holiday": is_holiday,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error checking holiday: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred while checking holiday status"},
            500,
        )
