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


"""Deterministic contracts for Sprint 14 Decision Intelligence."""


from dataclasses import dataclass, field
from datetime import date

_ALLOWED_SCOPES = {"COMPANY", "OPPORTUNITY", "PORTFOLIO", "MARKET"}
_ALLOWED_ACTIONS = {"BUY", "ADD", "HOLD", "REDUCE", "EXIT", "WATCH", "NO_ACTION"}
_ALLOWED_STATUSES = {"READY", "PARTIAL", "INSUFFICIENT_DATA", "CONFLICTING_EVIDENCE"}
_ALLOWED_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


@dataclass(frozen=True)
class DecisionInput:
    decision_id: str
    scope: str
    as_of_date: str
    subject: str
    evidence_references: tuple[str, ...] = ()
    source_modules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            msg = "decision_id is required"
            raise ValueError(msg)
        if self.scope not in _ALLOWED_SCOPES:
            msg = f"Unsupported decision scope: {self.scope}"
            raise ValueError(msg)
        date.fromisoformat(self.as_of_date)
        if not self.subject.strip():
            msg = "subject is required"
            raise ValueError(msg)
        if len(set(self.evidence_references)) != len(self.evidence_references):
            msg = "evidence_references must be unique"
            raise ValueError(msg)
        if len(set(self.source_modules)) != len(self.source_modules):
            msg = "source_modules must be unique"
            raise ValueError(msg)


@dataclass(frozen=True)
class DecisionRecommendation:
    decision_id: str
    generated_date: str
    status: str
    action: str
    confidence: str
    score: float | None = None
    rationale: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    component_scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            msg = "decision_id is required"
            raise ValueError(msg)
        date.fromisoformat(self.generated_date)
        if self.status not in _ALLOWED_STATUSES:
            msg = f"Unsupported decision status: {self.status}"
            raise ValueError(msg)
        if self.action not in _ALLOWED_ACTIONS:
            msg = f"Unsupported decision action: {self.action}"
            raise ValueError(msg)
        if self.confidence not in _ALLOWED_CONFIDENCE:
            msg = f"Unsupported confidence: {self.confidence}"
            raise ValueError(msg)
        if self.score is not None and not 0 <= self.score <= 100:
            msg = "score must be between 0 and 100"
            raise ValueError(msg)
        for name, value in self.component_scores.items():
            if not name.strip():
                msg = "component score names cannot be blank"
                raise ValueError(msg)
            if not 0 <= value <= 100:
                msg = "component scores must be between 0 and 100"
                raise ValueError(msg)
        if len(set(self.evidence_references)) != len(self.evidence_references):
            msg = "evidence_references must be unique"
            raise ValueError(msg)
        if self.status == "READY":
            if not self.evidence_references:
                msg = "READY decisions require evidence references"
                raise ValueError(msg)
            if not self.rationale:
                msg = "READY decisions require rationale"
                raise ValueError(msg)
            if self.score is None:
                msg = "READY decisions require a deterministic score"
                raise ValueError(msg)
        if self.status in {"INSUFFICIENT_DATA", "CONFLICTING_EVIDENCE"}:
            if self.action not in {"WATCH", "NO_ACTION"}:
                msg = "Unresolved decisions cannot recommend portfolio-changing actions"
                raise ValueError(msg)
            if not self.limitations:
                msg = "Unresolved decisions require limitations"
                raise ValueError(msg)
        if self.action in {"BUY", "ADD", "REDUCE", "EXIT"} and self.status != "READY":
            msg = "Portfolio-changing actions require READY status"
            raise ValueError(msg)
