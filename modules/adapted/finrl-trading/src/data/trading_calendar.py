import contextlib
import datetime
import logging
from datetime import date, datetime
from functools import lru_cache
from typing import List, Optional, Set, Tuple

import pytz

logger = logging.getLogger(__name__)

# Try to import tzlocal
try:
    import tzlocal

    _tzlocal_available = True
except ImportError:
    _tzlocal_available = False
    logger.debug("tzlocal not available, using fallback timezone detection")

# Try to import market calendar libraries
_calendar_lib: str | None = None
_nyse_calendar = None
_mcal = None
_xcals = None

try:
    import pandas_market_calendars as mcal

    _mcal = mcal
    _calendar_lib = "pandas_market_calendars"
    _nyse_calendar = mcal.get_calendar("NYSE")
    logger.info("Using pandas_market_calendars for trading calendar")
except ImportError:
    try:
        import exchange_calendars as xcals

        _xcals = xcals
        _calendar_lib = "exchange_calendars"
        _nyse_calendar = xcals.get_calendar("XNYS")
        logger.info("Using exchange_calendars for trading calendar")
    except ImportError:
        logger.warning("Neither pandas_market_calendars nor exchange_calendars found. Using basic calendar logic.")
        logger.warning("Install with: pip install pandas-market-calendars  OR  pip install exchange-calendars")


def is_ist_market_session_active(dt: datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.now(ist)
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


@lru_cache(maxsize=32)
def _get_calendar_cached(exchange: str):
    if _calendar_lib == "pandas_market_calendars" and _mcal:
        return _mcal.get_calendar(exchange)
    if _calendar_lib == "exchange_calendars" and _xcals:
        return _xcals.get_calendar(exchange)
    msg = "No calendar library available"
    raise RuntimeError(msg)


@lru_cache(maxsize=256)
def _cached_trading_days(exchange: str, start_date: str, end_date: str) -> tuple[str, ...]:
    cal = _get_calendar_cached(exchange)
    tzinfo = "UTC"
    try:
        if _tzlocal_available:
            tzinfo = tzlocal.get_localzone_name()
    except Exception:
        with contextlib.suppress(Exception):
            tzinfo = datetime.now().astimezone().tzname() or "UTC"
    schedule = cal.schedule(start_date=start_date, end_date=end_date, tz=tzinfo)
    return tuple(schedule.index.strftime("%Y-%m-%d").tolist())


def get_trading_days(start_date: str, end_date: str, exchange: str = "NYSE") -> list[str]:
    """Get list of trading days between start_date and end_date inclusive."""
    if _calendar_lib is None:
        # Fallback: basic weekday logic
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        days = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # Mon-Fri
                days.append(current.strftime("%Y-%m-%d"))
            current += datetime.timedelta(days=1)
        return days
    return list(_cached_trading_days(exchange, start_date, end_date))
