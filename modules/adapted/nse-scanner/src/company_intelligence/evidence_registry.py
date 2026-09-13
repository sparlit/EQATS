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


"""Deterministic validation, deduplication, and query services for company evidence."""


import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import EvidenceItem

_ALLOWED_CATEGORIES = {
    "TECHNICAL",
    "FINANCIAL",
    "VALUATION",
    "OWNERSHIP",
    "GOVERNANCE",
    "CORPORATE_ACTION",
    "CORPORATE_ANNOUNCEMENT",
    "NEWS",
    "RISK",
    "RATING",
}


@dataclass(frozen=True)
class RegisteredEvidence:
    """Evidence stored with immutable registry metadata."""

    symbol: str
    evidence_id: str
    item: EvidenceItem

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "evidence_id": self.evidence_id,
            "item": asdict(self.item),
        }


class EvidenceRegistry:
    """In-memory deterministic evidence registry.

    Persistence is delegated to ``EvidenceRepository``. The registry never
    infers facts and accepts only explicit, provenance-backed records.
    """

    def __init__(self, records: Iterable[RegisteredEvidence] = ()) -> None:
        self._records: dict[str, RegisteredEvidence] = {}
        for record in records:
            self._records[record.evidence_id] = record

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            msg = "symbol is required"
            raise ValueError(msg)
        return normalized

    @staticmethod
    def _validate(item: EvidenceItem, *, today: date | None = None) -> None:
        if item.category not in _ALLOWED_CATEGORIES:
            msg = f"Unsupported evidence category: {item.category}"
            raise ValueError(msg)
        if item.status == "VERIFIED" and not item.source_reference.strip():
            msg = "Verified evidence requires source_reference"
            raise ValueError(msg)
        observed = date.fromisoformat(item.as_of_date)
        if observed > (today or date.today()):
            msg = "Evidence as_of_date cannot be in the future"
            raise ValueError(msg)

    @staticmethod
    def _fingerprint(symbol: str, item: EvidenceItem) -> str:
        canonical = json.dumps(
            {"symbol": symbol, "item": asdict(item)},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def register(
        self,
        symbol: str,
        item: EvidenceItem,
        *,
        today: date | None = None,
    ) -> RegisteredEvidence:
        normalized = self._normalize_symbol(symbol)
        self._validate(item, today=today)
        evidence_id = self._fingerprint(normalized, item)
        if evidence_id in self._records:
            msg = f"Duplicate evidence: {evidence_id}"
            raise ValueError(msg)
        record = RegisteredEvidence(normalized, evidence_id, item)
        self._records[evidence_id] = record
        return record

    def all(self, symbol: str | None = None) -> tuple[RegisteredEvidence, ...]:
        records = tuple(self._records.values())
        if symbol is None:
            return records
        normalized = self._normalize_symbol(symbol)
        return tuple(record for record in records if record.symbol == normalized)

    def by_category(self, symbol: str, category: str) -> tuple[RegisteredEvidence, ...]:
        return tuple(record for record in self.all(symbol) if record.item.category == category)

    def latest(self, symbol: str, category: str | None = None) -> RegisteredEvidence | None:
        records = self.by_category(symbol, category) if category else self.all(symbol)
        if not records:
            return None
        return max(records, key=lambda record: (record.item.as_of_date, record.evidence_id))

    def stale(self, *, max_age_days: int, today: date | None = None) -> tuple[RegisteredEvidence, ...]:
        if max_age_days < 0:
            msg = "max_age_days cannot be negative"
            raise ValueError(msg)
        reference_date = today or date.today()
        return tuple(
            record
            for record in self._records.values()
            if (reference_date - date.fromisoformat(record.item.as_of_date)).days > max_age_days
        )
