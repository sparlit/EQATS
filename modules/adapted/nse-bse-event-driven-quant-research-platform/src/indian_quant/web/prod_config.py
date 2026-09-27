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


"""Production configuration for PostgreSQL + Redis.

This module re-exports from config.connections for backward compatibility.
New code should import from indian_quant.config.connections directly.
"""

from indian_quant.config.connections import (
    PG_DSN,
    REDIS_TTL,
    REDIS_URL,
    ensure_schema,
    get_engine,
    get_redis,
)

# Backward-compatible alias
get_pg_engine = get_engine
get_redis_client = get_redis

__all__ = [
    "PG_DSN",
    "REDIS_TTL",
    "REDIS_URL",
    "ensure_schema",
    "get_engine",
    "get_pg_engine",
    "get_redis",
    "get_redis_client",
]
