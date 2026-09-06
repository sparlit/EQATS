"""
Expiry Manager — DTE calculation, expiry classification.
"""

from datetime import date, timedelta

import utils.upstox_data as ud
from utils.logger import get_logger

log = get_logger("expiry_mgr")


def get_dte(expiry_str: str) -> int:
    """Days to expiry from today. 0 = expiring today, negative = expired."""
    return (date.fromisoformat(expiry_str) - date.today()).days


def is_expiry_day(symbol: str) -> bool:
    nearest = ud.get_nearest_expiry(symbol)
    if not nearest:
        return False
    return get_dte(nearest) == 0


def get_next_expiry(symbol: str) -> str | None:
    """Get the expiry after the nearest one."""
    expiries = ud.get_expiry_dates(symbol)
    if len(expiries) >= 2:
        return expiries[1]
    return _fallback_next_expiry(symbol)


WEEKLY_SYMBOLS = {"NIFTY"}


def _last_tuesday_of_month(year: int, month: int) -> date:
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    d = first_next - timedelta(days=1)
    while d.weekday() != 1:
        d -= timedelta(days=1)
    return d


def _fallback_next_expiry(symbol: str) -> str:
    d = date.today() + timedelta(days=2)
    if symbol in WEEKLY_SYMBOLS:
        while d.weekday() != 1:
            d += timedelta(days=1)
        return d.isoformat()
    exp = _last_tuesday_of_month(d.year, d.month)
    if exp >= d:
        return exp.isoformat()
    if d.month == 12:
        return _last_tuesday_of_month(d.year + 1, 1).isoformat()
    return _last_tuesday_of_month(d.year, d.month + 1).isoformat()
