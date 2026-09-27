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


"""NSE trading calendar.

Static seed of exchange holidays (2024-2027). The 2026 float dates were
empirically confirmed against live NSE bhavcopy availability during the
Aug-2026 ingestion run. The seed requires an annual refresh - documented
in docs/operations.md; a best-effort MCP refresh hook exists but falls
back to this table on any failure.
"""


from datetime import date

FIXED_HOLIDAYS: dict[int, set[tuple[int, int]]] = {
    2024: {
        (1, 22),
        (1, 25),
        (1, 26),
        (3, 8),
        (3, 25),
        (3, 29),
        (4, 11),
        (4, 17),
        (5, 1),
        (5, 20),
        (6, 17),
        (7, 17),
        (8, 15),
        (10, 2),
        (11, 1),
        (11, 15),
        (11, 20),
        (12, 25),
    },
    2025: {
        (2, 26),
        (3, 14),
        (3, 31),
        (4, 10),
        (4, 14),
        (4, 18),
        (5, 1),
        (8, 15),
        (8, 27),
        (10, 2),
        (10, 21),
        (10, 22),
        (11, 5),
        (12, 25),
    },
    2026: {
        (1, 15),
        (1, 26),
        (3, 3),
        (3, 4),
        (3, 21),
        (3, 26),
        (4, 1),
        (4, 3),
        (4, 14),
        (5, 1),
        (5, 28),
        (6, 26),
        (8, 15),
        (8, 28),
        (10, 2),
        (10, 20),
        (11, 9),
        (11, 24),
        (12, 25),
    },
    2027: {(1, 26), (3, 26), (5, 1), (8, 15), (10, 2), (11, 15), (12, 27)},
}


class NSECalendar:
    """Weekend + holiday trading-day logic for the National Stock Exchange."""

    def __init__(self, extra_holidays: set[date] | None = None) -> None:
        self._extra = extra_holidays or set()

    def holidays(self, year: int | None = None) -> set[date]:
        if year is not None:
            days = {date(year, m, d) for m, d in FIXED_HOLIDAYS.get(year, set())}
        else:
            days = {date(y, m, d) for y, md in FIXED_HOLIDAYS.items() for m, d in md}
        return days | {d for d in self._extra if year is None or d.year == year}

    def is_holiday(self, day: date) -> bool:
        return day in self.holidays(day.year)

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and not self.is_holiday(day)

    def trading_days_between(self, start: date, end: date) -> list[date]:
        out: list[date] = []
        cursor = start
        while cursor <= end:
            if self.is_trading_day(cursor):
                out.append(cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return out


_default_calendar: NSECalendar | None = None


def default_calendar() -> NSECalendar:
    global _default_calendar
    if _default_calendar is None:
        _default_calendar = NSECalendar()
    return _default_calendar
