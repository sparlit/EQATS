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


"""Monthly portfolio intelligence package.

Sprint 8 adds a review layer for active portfolio positions without changing the
existing daily scanner or portfolio lifecycle.
"""

from .evidence_collector import collect_evidence
from .portfolio_reader import build_review_queue, load_active_positions
from .prompt_builder import PROMPT_VERSION, build_review_prompt
from .review_repository import load_latest_review, save_review
from .review_validator import assert_valid_review, validate_review

__all__ = [
    "PROMPT_VERSION",
    "assert_valid_review",
    "build_review_prompt",
    "build_review_queue",
    "collect_evidence",
    "load_active_positions",
    "load_latest_review",
    "save_review",
    "validate_review",
]
