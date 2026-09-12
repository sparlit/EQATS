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


"""Review-age, caching and cost-control policies for portfolio intelligence."""

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from .review_repository import load_latest_review

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ReviewPolicy:
    max_age_days: int = 45
    max_symbols_per_run: int = 30
    max_provider_calls_per_run: int = 60
    force_refresh: bool = False

    @classmethod
    def from_env(cls) -> ReviewPolicy:
        return cls(
            max_age_days=max(1, int(os.getenv("PORTFOLIO_REVIEW_MAX_AGE_DAYS", "45"))),
            max_symbols_per_run=max(0, int(os.getenv("PORTFOLIO_REVIEW_MAX_SYMBOLS", "30"))),
            max_provider_calls_per_run=max(0, int(os.getenv("PORTFOLIO_REVIEW_MAX_PROVIDER_CALLS", "60"))),
            force_refresh=os.getenv("PORTFOLIO_REVIEW_FORCE_REFRESH", "false").lower() in {"1", "true", "yes"},
        )


def _parse_review_date(review: dict[str, Any] | None) -> date | None:
    if not review:
        return None
    raw = str(review.get("review_date", ""))
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def review_age_days(review: dict[str, Any] | None, *, as_of: date | None = None) -> int | None:
    reviewed = _parse_review_date(review)
    if reviewed is None:
        return None
    return max(0, ((as_of or date.today()) - reviewed).days)


def should_review_symbol(
    symbol: str,
    *,
    reports_root: str | Path = "reports/portfolio",
    policy: ReviewPolicy | None = None,
    as_of: date | None = None,
) -> tuple[bool, str]:
    active_policy = policy or ReviewPolicy.from_env()
    if active_policy.force_refresh:
        return True, "forced refresh"
    latest = load_latest_review(symbol, reports_root=reports_root)
    age = review_age_days(latest, as_of=as_of)
    if age is None:
        return True, "no valid prior review"
    if age >= active_policy.max_age_days:
        return True, f"review is {age} days old"
    return False, f"cached review is fresh ({age} days old)"
