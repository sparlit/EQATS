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


"""Indian market trading day utilities.

Counts actual NSE trading days excluding weekends and Indian market holidays.
"""


from datetime import date, timedelta

# Major Indian market holidays (NSE/BSE) — update yearly
INDIAN_HOLIDAYS = {
    2025: [
        date(2025, 1, 26),  # Republic Day
        date(2025, 3, 14),  # Holi
        date(2025, 3, 31),  # Eid ul-Fitr
        date(2025, 4, 10),  # Shri Mahavir Jayanti
        date(2025, 4, 14),  # Dr. Ambedkar Jayanti
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 1),  # Maharashtra Day
        date(2025, 6, 7),  # Bakri Id
        date(2025, 8, 15),  # Independence Day
        date(2025, 8, 27),  # Ganesh Chaturthi
        date(2025, 10, 2),  # Mahatma Gandhi Jayanti
        date(2025, 10, 21),  # Diwali Laxmi Pujan
        date(2025, 10, 22),  # Diwali Balipratipada
        date(2025, 11, 5),  # Prakash Gurpurab
        date(2025, 12, 25),  # Christmas
    ],
    2026: [
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 4),  # Holi
        date(2026, 3, 20),  # Eid ul-Fitr (approx)
        date(2026, 3, 30),  # Shri Mahavir Jayanti (approx)
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 14),  # Dr. Ambedkar Jayanti
        date(2026, 5, 1),  # Maharashtra Day
        date(2026, 5, 27),  # Bakri Id (approx)
        date(2026, 8, 15),  # Independence Day
        date(2026, 9, 16),  # Ganesh Chaturthi (approx)
        date(2026, 10, 2),  # Mahatma Gandhi Jayanti
        date(2026, 11, 10),  # Diwali (approx)
        date(2026, 11, 11),  # Diwali Balipratipada (approx)
        date(2026, 11, 24),  # Prakash Gurpurab (approx)
        date(2026, 12, 25),  # Christmas
    ],
}


def is_trading_day(d: date) -> bool:
    """Check if a date is a likely NSE trading day (weekday + not holiday)."""
    if d.weekday() >= 5:  # Saturday or Sunday
        return False
    year_holidays = INDIAN_HOLIDAYS.get(d.year, [])
    return d not in year_holidays


def trade_days_between(start: date, end: date) -> int:
    """Count NSE trading days between start and end (inclusive of both)."""
    if start > end:
        start, end = end, start
    count = 0
    current = start
    while current <= end:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def next_trading_day(d: date) -> date:
    """Get the next trading day after d."""
    next_d = d + timedelta(days=1)
    while not is_trading_day(next_d):
        next_d += timedelta(days=1)
    return next_d


def prev_trading_day(d: date) -> date:
    """Get the previous trading day before d."""
    prev_d = d - timedelta(days=1)
    while not is_trading_day(prev_d):
        prev_d -= timedelta(days=1)
    return prev_d
