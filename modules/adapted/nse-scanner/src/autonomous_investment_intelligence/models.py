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


"""Deterministic contracts for Sprint 15 Autonomous Investment Intelligence."""


from dataclasses import dataclass, field
from datetime import date

_ALLOWED_SCOPES = {"COMPANY", "OPPORTUNITY", "PORTFOLIO", "MARKET"}
_ALLOWED_CYCLE_STATUSES = {
    "READY_FOR_REVIEW",
    "AWAITING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "INSUFFICIENT_DATA",
    "CONFLICTING_EVIDENCE",
}
_ALLOWED_ACTIONS = {"BUY", "ADD", "HOLD", "REDUCE", "EXIT", "WATCH", "NO_ACTION"}
_ALLOWED_APPROVAL_DECISIONS = {"APPROVE", "REJECT", "DEFER"}
_ALLOWED_OUTCOMES = {"EXECUTED", "NOT_EXECUTED", "EXPIRED", "CANCELLED"}
_PORTFOLIO_CHANGING_ACTIONS = {"BUY", "ADD", "REDUCE", "EXIT"}


@dataclass(frozen=True)
class AutonomousDecisionCycle:
    cycle_id: str
    decision_id: str
    scope: str
    as_of_date: str
    action: str
    status: str
    evidence_references: tuple[str, ...] = ()
    deterministic_score: float | None = None
    constraints: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    expires_on: str | None = None

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        if not self.decision_id.strip():
            raise ValueError("decision_id is required")
        if self.scope not in _ALLOWED_SCOPES:
            raise ValueError(f"Unsupported autonomous scope: {self.scope}")
        date.fromisoformat(self.as_of_date)
        if self.action not in _ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported autonomous action: {self.action}")
        if self.status not in _ALLOWED_CYCLE_STATUSES:
            raise ValueError(f"Unsupported cycle status: {self.status}")
        if self.deterministic_score is not None and not 0 <= self.deterministic_score <= 100:
            raise ValueError("deterministic_score must be between 0 and 100")
        if len(set(self.evidence_references)) != len(self.evidence_references):
            raise ValueError("evidence_references must be unique")
        if self.expires_on is not None:
            expiry = date.fromisoformat(self.expires_on)
            if expiry < date.fromisoformat(self.as_of_date):
                raise ValueError("expires_on cannot precede as_of_date")
        if self.status in {"READY_FOR_REVIEW", "AWAITING_APPROVAL", "APPROVED"}:
            if not self.evidence_references:
                raise ValueError("Actionable cycles require evidence references")
            if self.deterministic_score is None:
                raise ValueError("Actionable cycles require a deterministic score")
        if self.status in {"INSUFFICIENT_DATA", "CONFLICTING_EVIDENCE"}:
            if self.action not in {"WATCH", "NO_ACTION"}:
                raise ValueError("Unresolved cycles cannot propose portfolio-changing actions")
            if not self.limitations:
                raise ValueError("Unresolved cycles require limitations")
        if self.action in _PORTFOLIO_CHANGING_ACTIONS and self.status == "APPROVED":
            if not self.constraints:
                raise ValueError("Approved portfolio-changing actions require constraints")


@dataclass(frozen=True)
class HumanApproval:
    cycle_id: str
    reviewer: str
    reviewed_date: str
    decision: str
    reason: str
    approval_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        if not self.reviewer.strip():
            raise ValueError("reviewer is required")
        date.fromisoformat(self.reviewed_date)
        if self.decision not in _ALLOWED_APPROVAL_DECISIONS:
            raise ValueError(f"Unsupported approval decision: {self.decision}")
        if not self.reason.strip():
            raise ValueError("approval reason is required")
        if self.decision == "APPROVE" and not (self.approval_reference or "").strip():
            raise ValueError("Approved decisions require an approval_reference")


@dataclass(frozen=True)
class AutonomousDecisionOutcome:
    cycle_id: str
    recorded_date: str
    outcome: str
    executed_action: str = "NO_ACTION"
    approval_reference: str | None = None
    audit_references: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        date.fromisoformat(self.recorded_date)
        if self.outcome not in _ALLOWED_OUTCOMES:
            raise ValueError(f"Unsupported outcome: {self.outcome}")
        if self.executed_action not in _ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported executed action: {self.executed_action}")
        if len(set(self.audit_references)) != len(self.audit_references):
            raise ValueError("audit_references must be unique")
        if self.outcome == "EXECUTED":
            if self.executed_action not in _PORTFOLIO_CHANGING_ACTIONS:
                raise ValueError("EXECUTED outcomes require a portfolio-changing action")
            if not (self.approval_reference or "").strip():
                raise ValueError("EXECUTED outcomes require an approval_reference")
            if not self.audit_references:
                raise ValueError("EXECUTED outcomes require audit references")
        elif self.executed_action != "NO_ACTION":
            raise ValueError("Non-executed outcomes must use NO_ACTION")
