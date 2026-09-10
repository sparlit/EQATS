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
Utility modules for Adaptive Rotation Strategy
"""

from .calendar_utils import (
    align_to_trading_day,
    get_available_exchanges,
    get_next_trading_day,
    get_previous_trading_day,
    get_trading_calendar,
    get_week_end_dates,
    is_trading_day,
    trading_days_between,
)
from .robust_stats import (
    compute_information_ratio,
    compute_mad,
    detect_outliers_mad,
    robust_zscore,
    scale_mad_to_std,
    winsorize_by_mad,
)

__all__ = [
    "align_to_trading_day",
    "compute_information_ratio",
    # Robust stats
    "compute_mad",
    "detect_outliers_mad",
    "get_available_exchanges",
    "get_next_trading_day",
    "get_previous_trading_day",
    # Calendar utils
    "get_trading_calendar",
    "get_week_end_dates",
    "is_trading_day",
    "robust_zscore",
    "scale_mad_to_std",
    "trading_days_between",
    "winsorize_by_mad",
]
