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


"""Real IST timestamps for the ideas tool (scripts/ideas/*).

The daily routine runs on a cloud VM whose clock is UTC; the user's Mac runs IST. So
`datetime.datetime.now().strftime('... IST')` — what every builder here used to do — wrote a
UTC time wearing an IST label on every cloud run: signals.json was stamped "2026-09-22 14:06 IST"
for a run that happened at 19:36 IST. Every timestamp and every "today" these scripts write now
goes through this module, so the label is always true wherever the script runs.

Stdlib only and no tzdata lookup: IST is a fixed UTC+05:30 with no daylight saving.
"""
import datetime

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")


def now():
    """Timezone-aware 'now' in IST."""
    return datetime.datetime.now(IST)


def stamp():
    """'YYYY-MM-DD HH:MM IST' — the timestamp format this repo writes everywhere (CLAUDE.md)."""
    return now().strftime("%Y-%m-%d %H:%M IST")


def today():
    """Today's date in IST — not the container's date, which is a day behind before 05:30 IST."""
    return now().date()
