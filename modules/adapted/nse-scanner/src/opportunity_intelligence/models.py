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


"""Deterministic contracts for MIS opportunity intelligence."""


from dataclasses import dataclass, field
from datetime import date
from typing import Any

_ALLOWED_OPPORTUNITY_STATUS = {"QUALIFIED", "WATCHLIST", "REJECTED", "INSUFFICIENT_DATA"}
_ALLOWED_HORIZONS = {"SHORT", "SWING", "POSITIONAL", "LONG_TERM"}
_ALLOWED_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


@dataclass(frozen=True)
class OpportunityEvidence:
    evidence_id: str
    category: str
    as_of_date: str
    source_reference: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            msg = "evidence_id is required"
            raise ValueError(msg)
        if not self.category.strip():
            msg = "category is required"
            raise ValueError(msg)
        if not self.source_reference.strip():
            msg = "source_reference is required"
            raise ValueError(msg)
        date.fromisoformat(self.as_of_date)


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    generated_date: str
    status: str
    horizon: str
    confidence: str
    score: float
    evidence_ids: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            msg = "symbol is required"
            raise ValueError(msg)
        date.fromisoformat(self.generated_date)
        if self.status not in _ALLOWED_OPPORTUNITY_STATUS:
            msg = f"Unsupported opportunity status: {self.status}"
            raise ValueError(msg)
        if self.horizon not in _ALLOWED_HORIZONS:
            msg = f"Unsupported horizon: {self.horizon}"
            raise ValueError(msg)
        if self.confidence not in _ALLOWED_CONFIDENCE:
            msg = f"Unsupported confidence: {self.confidence}"
            raise ValueError(msg)
        if not 0 <= self.score <= 100:
            msg = "score must be between 0 and 100"
            raise ValueError(msg)
        if self.status == "QUALIFIED" and not self.evidence_ids:
            msg = "Qualified opportunities require evidence"
            raise ValueError(msg)
        if self.status == "INSUFFICIENT_DATA" and self.confidence == "HIGH":
            msg = "Insufficient-data opportunities cannot have HIGH confidence"
            raise ValueError(msg)
