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


"""Domain models and controlled values for portfolio reviews."""


from dataclasses import asdict, dataclass, field
from typing import Any

TECHNICAL_STATUSES = {"BULLISH", "NEUTRAL", "WEAK", "BROKEN"}
FUNDAMENTAL_STATUSES = {"HEALTHY", "STABLE", "WATCH", "CONCERN", "NOT_REVIEWED"}
MANAGEMENT_STATUSES = {"POSITIVE", "STABLE", "WATCH", "CONCERN", "UNKNOWN"}
RISK_STATUSES = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
ACTIONS = {
    "HOLD",
    "WATCH",
    "REVIEW",
    "REDUCE",
    "TECHNICAL_EXIT",
    "INSUFFICIENT_DATA",
}
EVIDENCE_STATUSES = {"COMPLETE", "PARTIAL", "TECHNICAL_ONLY", "FAILED"}


@dataclass(frozen=True)
class ReviewQueueItem:
    symbol: str
    position: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioReview:
    symbol: str
    review_date: str
    review_period: str
    technical_status: str
    fundamental_status: str = "NOT_REVIEWED"
    management_status: str = "UNKNOWN"
    risk_status: str = "UNKNOWN"
    suggested_action: str = "INSUFFICIENT_DATA"
    material_change: bool = False
    confidence_score: float = 0.0
    summary: str = ""
    key_positives: list[str] = field(default_factory=list)
    key_concerns: list[str] = field(default_factory=list)
    evidence_status: str = "TECHNICAL_ONLY"
    data_limitations: list[str] = field(default_factory=list)
    prompt_version: str = "portfolio_review_v1"
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
