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


from datetime import date

import pytest
from src.company_intelligence.evidence_registry import EvidenceRegistry
from src.company_intelligence.evidence_repository import EvidenceRepository
from src.company_intelligence.models import EvidenceItem


def _item(**overrides: object) -> EvidenceItem:
    values: dict[str, object] = {
        "source_id": "nse-technical-1",
        "category": "TECHNICAL",
        "as_of_date": "2026-07-30",
        "status": "VERIFIED",
        "payload": {"trend": "UP"},
        "source_reference": "scanner/output.json",
    }
    values.update(overrides)
    return EvidenceItem(**values)  # type: ignore[arg-type]


def test_register_and_query_latest() -> None:
    registry = EvidenceRegistry()
    older = registry.register(
        "infy",
        _item(source_id="old", as_of_date="2026-07-20"),
        today=date(2026, 7, 31),
    )
    newer = registry.register(
        "INFY",
        _item(source_id="new", as_of_date="2026-07-30"),
        today=date(2026, 7, 31),
    )

    assert older.symbol == "INFY"
    assert registry.latest("infy") == newer
    assert len(registry.by_category("INFY", "TECHNICAL")) == 2


def test_duplicate_evidence_is_rejected() -> None:
    registry = EvidenceRegistry()
    item = _item()
    registry.register("TCS", item, today=date(2026, 7, 31))

    with pytest.raises(ValueError, match="Duplicate evidence"):
        registry.register("TCS", item, today=date(2026, 7, 31))


def test_verified_evidence_requires_provenance() -> None:
    registry = EvidenceRegistry()
    with pytest.raises(ValueError, match="source_reference"):
        registry.register(
            "TCS",
            _item(source_reference=""),
            today=date(2026, 7, 31),
        )


def test_future_and_unsupported_evidence_are_rejected() -> None:
    registry = EvidenceRegistry()
    with pytest.raises(ValueError, match="future"):
        registry.register(
            "TCS",
            _item(as_of_date="2026-08-01"),
            today=date(2026, 7, 31),
        )
    with pytest.raises(ValueError, match="category"):
        registry.register(
            "TCS",
            _item(category="RUMOUR"),
            today=date(2026, 7, 31),
        )


def test_stale_query() -> None:
    registry = EvidenceRegistry()
    stale = registry.register(
        "TCS",
        _item(as_of_date="2026-06-01"),
        today=date(2026, 7, 31),
    )
    registry.register(
        "INFY",
        _item(source_id="fresh", as_of_date="2026-07-30"),
        today=date(2026, 7, 31),
    )

    assert registry.stale(max_age_days=30, today=date(2026, 7, 31)) == (stale,)


def test_repository_round_trip_is_append_only(tmp_path) -> None:
    registry = EvidenceRegistry()
    record = registry.register(
        "RELIANCE",
        _item(),
        today=date(2026, 7, 31),
    )
    repository = EvidenceRepository(tmp_path)
    path = repository.save(record)

    assert path.exists()
    assert repository.load_all("RELIANCE") == (record,)
    with pytest.raises(FileExistsError):
        repository.save(record)
