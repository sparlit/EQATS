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


"""V2 data-retention and freshness policy.

V1 loader behavior is intentionally unchanged. V2 reads the existing seed
history and manages its own retention/freshness controls.
"""

import os

SEED_HISTORY_SESSIONS = int(os.getenv("V2_SEED_HISTORY_SESSIONS", "420"))
MIN_INDICATOR_SESSIONS = int(os.getenv("V2_MIN_INDICATOR_SESSIONS", "260"))
MIN_FULL_RANKING_SESSIONS = int(os.getenv("V2_MIN_FULL_RANKING_SESSIONS", "400"))
RECENT_REPAIR_SESSIONS = int(os.getenv("V2_RECENT_REPAIR_SESSIONS", "5"))


def validate_policy() -> None:
    if SEED_HISTORY_SESSIONS < MIN_FULL_RANKING_SESSIONS:
        msg = "V2 seed history must cover full-ranking lookback"
        raise ValueError(msg)
    if MIN_FULL_RANKING_SESSIONS < MIN_INDICATOR_SESSIONS:
        msg = "full-ranking history must exceed indicator minimum"
        raise ValueError(msg)
    if RECENT_REPAIR_SESSIONS < 1:
        msg = "recent repair window must be positive"
        raise ValueError(msg)
