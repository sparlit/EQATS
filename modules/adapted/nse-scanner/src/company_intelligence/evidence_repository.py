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


"""Filesystem persistence for versioned company evidence."""


import json
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .evidence_registry import RegisteredEvidence
from .models import EvidenceItem

if TYPE_CHECKING:
    from collections.abc import Iterable


class EvidenceRepository:
    """Append-only JSON repository with symbol/category/date partitioning."""

    def __init__(self, root: str | Path = "company_data") -> None:
        self.root = Path(root)

    def save(self, record: RegisteredEvidence) -> Path:
        observed = record.item.as_of_date
        year, month, _ = observed.split("-")
        category = record.item.category.lower()
        directory = self.root / record.symbol / "evidence" / year / month
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{category}_{record.evidence_id[:16]}.json"
        if path.exists():
            msg = f"Evidence record already exists: {path}"
            raise FileExistsError(msg)

        payload = {
            **record.to_dict(),
            "stored_at": datetime.now(UTC).isoformat(),
            "schema_version": "company_evidence_v1",
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def load_all(self, symbol: str | None = None) -> tuple[RegisteredEvidence, ...]:
        base = self.root
        if symbol is not None:
            base = base / symbol.strip().upper()
        if not base.exists():
            return ()

        records: list[RegisteredEvidence] = []
        for path in sorted(base.glob("**/evidence/**/*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            item = EvidenceItem(**raw["item"])
            records.append(
                RegisteredEvidence(
                    symbol=raw["symbol"],
                    evidence_id=raw["evidence_id"],
                    item=item,
                )
            )
        return tuple(records)

    def save_many(self, records: Iterable[RegisteredEvidence]) -> tuple[Path, ...]:
        return tuple(self.save(record) for record in records)
