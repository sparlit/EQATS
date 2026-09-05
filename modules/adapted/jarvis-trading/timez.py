"""
Timezone helpers — single source of truth for IST.

NEVER use naive datetime.now() / date.today() in this project: cloud hosts
(Streamlit Cloud, GitHub Actions runners) run in UTC, so naive calls are off by
5h30m. Always use now_ist() / today_ist() for anything displayed or compared.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current timezone-aware datetime in Indian Standard Time."""
    return datetime.now(IST)


def today_ist() -> date:
    """Current calendar date in Indian Standard Time."""
    return datetime.now(IST).date()
