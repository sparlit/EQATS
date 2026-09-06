"""
Market Hours — session phases, holiday detection, trading windows.
"""

from datetime import date, datetime, timezone, timedelta

import utils.upstox_data as ud
from utils.logger import get_logger

log = get_logger("market_hours")

IST = timezone(timedelta(hours=5, minutes=30))

_PHASES = [
    ((9, 15),  (10, 0),  "OBSERVE"),
    ((10, 0),  (11, 30), "MORNING"),
    ((11, 30), (14, 0),  "AFTERNOON"),
    ((14, 0),  (15, 15), "CLOSING"),
    ((15, 15), (15, 30), "AUTO_CLOSE"),
]

_holiday_cache: dict = {"year": None, "dates": set()}


def _load_holidays() -> set[str]:
    year = date.today().year
    if _holiday_cache["year"] == year:
        return _holiday_cache["dates"]
    try:
        holidays = ud.get_market_holidays()
    except Exception as e:
        log.warning("Holiday API call failed: %s", e)
        holidays = []
    dates = set()
    for h in holidays:
        d = h.get("date", "")
        if d:
            dates.add(d[:10])
    if not dates:
        log.warning("No holidays loaded for %d", year)
        return dates
    _holiday_cache["year"] = year
    _holiday_cache["dates"] = dates
    log.info("Loaded %d holidays for %d", len(dates), year)
    return dates


def is_holiday(query_date: date | None = None) -> bool:
    if query_date is None:
        query_date = date.today()
    holidays = _load_holidays()
    return query_date.isoformat() in holidays


def is_weekend(query_date: date | None = None) -> bool:
    if query_date is None:
        query_date = date.today()
    return query_date.weekday() >= 5


def is_market_day(query_date: date | None = None) -> bool:
    if query_date is None:
        query_date = date.today()
    return not is_weekend(query_date) and not is_holiday(query_date)


def get_session_phase(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(IST)
    today = now.date() if hasattr(now, 'date') else date.today()
    if not is_market_day(today):
        return "CLOSED"
    t = (now.hour, now.minute)
    if t < (9, 15):
        return "PRE_MARKET"
    for (start_h, start_m), (end_h, end_m), phase in _PHASES:
        if (start_h, start_m) <= t < (end_h, end_m):
            return phase
    if t >= (15, 30):
        return "POST_MARKET"
    return "POST_MARKET"


def minutes_to_close(now: datetime | None = None) -> int:
    if now is None:
        now = datetime.now(IST)
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return int((close - now).total_seconds() / 60)


def next_trading_day(from_date: date | None = None) -> date:
    if from_date is None:
        from_date = date.today()
    d = from_date + timedelta(days=1)
    for _ in range(10):
        if is_market_day(d):
            return d
        d += timedelta(days=1)
    return d
