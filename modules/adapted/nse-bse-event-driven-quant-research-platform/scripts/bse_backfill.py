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


"""Backfill BSE bars_1d using multi-source router with fallback cascade.

Cascade: Upstox V3 (26 years) -> bseindia lib -> yfinance (3 months).

Uses SourceRouter for source orchestration and circuit breaker protection.

Usage:
    python scripts/bse_backfill.py              # backfill all BSE stocks
    python scripts/bse_backfill.py --limit 50   # backfill first 50 only
"""


import logging

logger = logging.getLogger(__name__)
