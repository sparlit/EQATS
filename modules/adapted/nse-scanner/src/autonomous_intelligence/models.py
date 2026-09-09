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


from dataclasses import dataclass, field
from typing import List, Optional

ALLOWED_STATUSES = {"PENDING", "READY", "BLOCKED", "REQUIRES_APPROVAL", "COMPLETED"}
ALLOWED_ACTIONS = {"OBSERVE", "RESEARCH", "REVIEW", "ALERT", "NO_ACTION"}


@dataclass(frozen=True)
class AutonomousTask:
    task_id: str
    symbol: str | None
    action: str
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "PENDING"
    requires_human_approval: bool = True

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            msg = "task_id is required"
            raise ValueError(msg)
        if self.action not in ALLOWED_ACTIONS:
            msg = "unsupported action"
            raise ValueError(msg)
        if self.status not in ALLOWED_STATUSES:
            msg = "unsupported status"
            raise ValueError(msg)
        if self.action != "NO_ACTION" and not self.evidence_refs:
            msg = "actionable tasks require evidence"
            raise ValueError(msg)
        if self.status == "COMPLETED" and self.requires_human_approval:
            msg = "approved execution must be recorded before completion"
            raise ValueError(msg)


@dataclass(frozen=True)
class AutonomousCycle:
    cycle_id: str
    generated_at: str
    tasks: list[AutonomousTask]
    execution_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            msg = "cycle_id is required"
            raise ValueError(msg)
        if self.execution_enabled:
            msg = "automated trade execution is not permitted"
            raise ValueError(msg)
