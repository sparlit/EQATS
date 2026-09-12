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


"""Point-in-time NSE corporate-data policies and calculations.

Submission/broadcast dates are deliberately separate from period end dates so
backtests cannot see a filing before it was available to the market.
"""

from dataclasses import dataclass

MARKET_CAP_MAX_AGE_DAYS = {
    "NSE_DIRECT_MARKET_CAP": 45,
    "DIRECT_SNAPSHOT": 45,
    "CALCULATED_QUARTERLY_SHARES": 120,
}


def market_cap_max_age_days(source: str) -> int:
    normalized = str(source or "DIRECT_SNAPSHOT").strip().upper()
    # Annual reports are classification/backfill evidence, never a live cap.
    if normalized == "NSE_ANNUAL_ALL_COMPANIES":
        return 0
    return MARKET_CAP_MAX_AGE_DAYS.get(normalized, 45)


def calculated_market_cap_cr(close: float, shares_outstanding: float) -> float:
    if close <= 0 or shares_outstanding <= 0:
        msg = "close and shares_outstanding must be positive"
        raise ValueError(msg)
    return close * shares_outstanding / 10_000_000.0


@dataclass(frozen=True)
class GovernanceEvent:
    event_type: str
    severity: str

    @property
    def hard_block(self) -> bool:
        return self.severity.upper() == "SEVERE"
