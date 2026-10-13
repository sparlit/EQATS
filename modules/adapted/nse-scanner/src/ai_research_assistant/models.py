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


"""Evidence-bound contracts for the MIS AI Research Assistant."""


from dataclasses import dataclass, field
from datetime import date

_ALLOWED_QUERY_TYPES = {"COMPANY", "COMPARISON", "SECTOR", "PORTFOLIO", "MARKET"}
_ALLOWED_STATUSES = {"READY", "PARTIAL", "INSUFFICIENT_DATA", "REJECTED"}
_ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}


@dataclass(frozen=True)
class ResearchQuery:
    query_id: str
    question: str
    query_type: str
    requested_date: str
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("query_id is required")
        if not self.question.strip():
            raise ValueError("question is required")
        if self.query_type not in _ALLOWED_QUERY_TYPES:
            raise ValueError(f"Unsupported query type: {self.query_type}")
        date.fromisoformat(self.requested_date)
        normalized = tuple(symbol.strip().upper() for symbol in self.symbols if symbol.strip())
        object.__setattr__(self, "symbols", normalized)


@dataclass(frozen=True)
class ResearchAnswer:
    query_id: str
    generated_date: str
    status: str
    confidence: str
    summary: str
    evidence_references: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    sections: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("query_id is required")
        date.fromisoformat(self.generated_date)
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(f"Unsupported answer status: {self.status}")
        if self.confidence not in _ALLOWED_CONFIDENCE:
            raise ValueError(f"Unsupported confidence: {self.confidence}")
        if self.status == "READY" and not self.evidence_references:
            raise ValueError("READY answers require evidence references")
        if self.status == "INSUFFICIENT_DATA" and self.confidence not in {"LOW", "UNKNOWN"}:
            raise ValueError("INSUFFICIENT_DATA answers cannot have medium or high confidence")
        if self.status != "REJECTED" and not self.summary.strip():
            raise ValueError("summary is required")
