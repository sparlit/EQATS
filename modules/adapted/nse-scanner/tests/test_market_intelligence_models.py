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


import pytest
from src.market_intelligence.models import MarketEvidence, MarketSnapshot


def test_verified_market_evidence_requires_provenance() -> None:
    with pytest.raises(ValueError):
        MarketEvidence(
            metric="ADVANCE_DECLINE_RATIO",
            as_of_date="2026-07-31",
            status="VERIFIED",
            value=1.4,
        )


def test_valid_verified_market_evidence() -> None:
    evidence = MarketEvidence(
        metric="ADVANCE_DECLINE_RATIO",
        as_of_date="2026-07-31",
        status="VERIFIED",
        value=1.4,
        source_reference="NSE daily market statistics",
    )
    assert evidence.value == 1.4


def test_market_snapshot_count_contract() -> None:
    with pytest.raises(ValueError):
        MarketSnapshot(
            as_of_date="2026-07-31",
            regime="NEUTRAL",
            evidence_count=1,
            verified_evidence_count=2,
        )


def test_insufficient_data_regime_is_explicit() -> None:
    snapshot = MarketSnapshot(
        as_of_date="2026-07-31",
        regime="INSUFFICIENT_DATA",
        evidence_count=0,
        verified_evidence_count=0,
        limitations=("Breadth evidence not supplied",),
    )
    assert snapshot.regime == "INSUFFICIENT_DATA"
