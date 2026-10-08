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


# utils/env_config.py
"""Tolerant readers for numeric environment settings.

Tuning values are read at module import time, so a plain ``int(os.getenv(...))``
turns a typo in ``.env`` into a worker that cannot start at all - the whole
platform down because a cache size was misspelled. These helpers fall back to
the default and log instead.
"""

import os

from utils.logging import get_logger

logger = get_logger(__name__)


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    """Read an integer setting, falling back to ``default`` if unusable."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(f"{name}={raw!r} is not an integer; using {default}")
            value = default
    if minimum is not None and value < minimum:
        logger.warning(f"{name}={value} is below the minimum {minimum}; using {minimum}")
        value = minimum
    return value


def env_float(name: str, default: float, minimum: float | None = None) -> float:
    """Read a float setting, falling back to ``default`` if unusable."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(f"{name}={raw!r} is not a number; using {default}")
            value = default
    if minimum is not None and value < minimum:
        logger.warning(f"{name}={value} is below the minimum {minimum}; using {minimum}")
        value = minimum
    return value
