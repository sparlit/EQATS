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


"""Session boundary helpers for sandbox position bookkeeping.

``sandbox_positions.updated_at`` is written by the database clock
(``func.now()``), which on the default SQLite database is UTC
(``CURRENT_TIMESTAMP``). ``SESSION_EXPIRY_TIME`` is a wall-clock time on
the host. Comparisons against position timestamps must resolve the
boundary in the database clock.
"""

from datetime import UTC, datetime, timedelta

from utils.logging import get_logger

logger = get_logger(__name__)

# Host session schedule is anchored to IST; a naive caller is treated as
# IST wall-clock so the boundary is never silently read as UTC or system time.
IST = pytz.timezone("Asia/Kolkata")


def as_db_utc(aware_local):
    """Convert a timezone-aware local datetime to the naive UTC the database stores.

    ``created_at`` and ``updated_at`` on the sandbox tables are naive DateTime
    columns written by ``func.now()``, which on SQLite is ``CURRENT_TIMESTAMP``,
    i.e. UTC. A naive IST value compared against them is not rejected, it is
    simply read as UTC, so the comparison silently skews by the offset. That is
    the same mistake twice over in this codebase: the MIS session boundary and
    the T+1 settlement cutoff were each 5.5 hours out. Route every local-to-column
    comparison through here rather than converting by hand at the call site.

    Args:
        aware_local: Timezone-aware datetime in any zone.

    Returns:
        Naive UTC datetime, directly comparable with the columns.
    """
    return aware_local.astimezone(UTC).replace(tzinfo=None)


def last_session_expiry_utc(session_expiry_str, now_local):
    """Resolve the most recent session boundary as a naive UTC datetime.

    Args:
        session_expiry_str: Wall-clock boundary from config (e.g. '03:00').
        now_local: Timezone-aware current time in the host's timezone.

    Returns:
        Naive UTC datetime of the most recent session expiry.
    """
    if now_local.tzinfo is None:
        logger.warning("last_session_expiry_utc received a naive datetime; assuming Asia/Kolkata")
        now_local = IST.localize(now_local)

    # Parse and range-check together. Splitting them leaves "25:00" parsing
    # cleanly as two ints and then raising from replace() below, which the
    # caller's broad `except Exception` swallows -- so a config typo silently
    # skips the MIS square-off instead of falling back.
    try:
        expiry_hour, expiry_minute = map(int, session_expiry_str.split(":"))
        boundary_today = now_local.replace(
            hour=expiry_hour, minute=expiry_minute, second=0, microsecond=0
        )
    except ValueError:
        logger.warning(
            f"Invalid SESSION_EXPIRY_TIME format: {session_expiry_str}. Using default 03:00"
        )
        boundary_today = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
    boundary = boundary_today if now_local >= boundary_today else boundary_today - timedelta(days=1)
    return as_db_utc(boundary)
