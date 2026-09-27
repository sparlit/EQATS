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


"""Deterministic contracts for MIS Portfolio Intelligence 2.0."""


from dataclasses import dataclass, field
from datetime import date

_ALLOWED_RISK_STATUS = {"LOW", "MODERATE", "HIGH", "INSUFFICIENT_DATA"}
_ALLOWED_ACTIONS = {"HOLD", "REDUCE", "INCREASE", "EXIT", "NO_ACTION"}


@dataclass(frozen=True)
class PortfolioRiskSnapshot:
    as_of_date: str
    position_count: int
    concentration_pct: float
    diversification_score: float
    risk_status: str
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        date.fromisoformat(self.as_of_date)
        if self.position_count < 0:
            msg = "position_count cannot be negative"
            raise ValueError(msg)
        if not 0 <= self.concentration_pct <= 100:
            msg = "concentration_pct must be between 0 and 100"
            raise ValueError(msg)
        if not 0 <= self.diversification_score <= 100:
            msg = "diversification_score must be between 0 and 100"
            raise ValueError(msg)
        if self.risk_status not in _ALLOWED_RISK_STATUS:
            msg = f"Unsupported risk status: {self.risk_status}"
            raise ValueError(msg)
        if self.risk_status != "INSUFFICIENT_DATA" and not self.evidence_ids:
            msg = "Evaluated risk requires evidence_ids"
            raise ValueError(msg)


@dataclass(frozen=True)
class RebalanceProposal:
    symbol: str
    action: str
    current_weight_pct: float
    proposed_weight_pct: float
    rationale_codes: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            msg = "symbol is required"
            raise ValueError(msg)
        if self.action not in _ALLOWED_ACTIONS:
            msg = f"Unsupported action: {self.action}"
            raise ValueError(msg)
        if not 0 <= self.current_weight_pct <= 100:
            msg = "current_weight_pct must be between 0 and 100"
            raise ValueError(msg)
        if not 0 <= self.proposed_weight_pct <= 100:
            msg = "proposed_weight_pct must be between 0 and 100"
            raise ValueError(msg)
        if self.action != "NO_ACTION" and not self.evidence_ids:
            msg = "Actionable proposals require evidence_ids"
            raise ValueError(msg)
        if self.action == "INCREASE" and self.proposed_weight_pct <= self.current_weight_pct:
            msg = "INCREASE requires a higher proposed weight"
            raise ValueError(msg)
        if self.action in {"REDUCE", "EXIT"} and self.proposed_weight_pct >= self.current_weight_pct:
            msg = f"{self.action} requires a lower proposed weight"
            raise ValueError(msg)
        if self.action == "EXIT" and self.proposed_weight_pct != 0:
            msg = "EXIT requires proposed_weight_pct of 0"
            raise ValueError(msg)
