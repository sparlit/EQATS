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


"""Core deterministic contracts for Sprint 9 company intelligence."""


from dataclasses import dataclass, field
from datetime import date
from typing import Any

_ALLOWED_EVIDENCE_STATUS = {"VERIFIED", "MISSING", "STALE", "REJECTED"}
_ALLOWED_DOSSIER_STATUS = {"READY", "PARTIAL", "INSUFFICIENT_DATA"}


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    category: str
    as_of_date: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_reference: str = ""

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            msg = "source_id is required"
            raise ValueError(msg)
        if not self.category.strip():
            msg = "category is required"
            raise ValueError(msg)
        if self.status not in _ALLOWED_EVIDENCE_STATUS:
            msg = f"Unsupported evidence status: {self.status}"
            raise ValueError(msg)
        date.fromisoformat(self.as_of_date)


@dataclass(frozen=True)
class CompanyDossier:
    symbol: str
    generated_date: str
    status: str
    evidence_count: int
    verified_evidence_count: int
    sections: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            msg = "symbol is required"
            raise ValueError(msg)
        date.fromisoformat(self.generated_date)
        if self.status not in _ALLOWED_DOSSIER_STATUS:
            msg = f"Unsupported dossier status: {self.status}"
            raise ValueError(msg)
        if self.evidence_count < 0 or self.verified_evidence_count < 0:
            msg = "Evidence counts cannot be negative"
            raise ValueError(msg)
        if self.verified_evidence_count > self.evidence_count:
            msg = "verified_evidence_count cannot exceed evidence_count"
            raise ValueError(msg)
