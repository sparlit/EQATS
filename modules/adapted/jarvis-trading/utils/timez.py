from __future__ import annotations

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


"""
Timezone helpers — single source of truth for IST.

NEVER use naive datetime.now() / date.today() in this project: cloud hosts
(Streamlit Cloud, GitHub Actions runners) run in UTC, so naive calls are off by
5h30m. Always use now_ist() / today_ist() for anything displayed or compared.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current timezone-aware datetime in Indian Standard Time."""
    return datetime.now(IST)


def today_ist() -> date:
    """Current calendar date in Indian Standard Time."""
    return datetime.now(IST).date()
