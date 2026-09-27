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


"""Configuration for the isolated Old NSE + Hull multi-horizon shadow run."""

import os


def shadow_enabled() -> bool:
    """Return whether the experimental engine is explicitly enabled.

    The default is deliberately off, so a normal Old NSE + Hull run remains
    byte-for-byte on its established baseline path.
    """
    return os.getenv("OLD_NSE_HULL_MULTI_HORIZON_MODE", "off").strip().lower() == "shadow"


MIN_HISTORY = 320
MIN_PRICE = 50.0
MIN_AVG_VOLUME = 50_000.0
QUALIFIED_SCORE = 65.0
CONFIRMING_SCORE = 55.0
