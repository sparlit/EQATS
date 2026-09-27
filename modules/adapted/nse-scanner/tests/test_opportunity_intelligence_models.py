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
from src.opportunity_intelligence.models import OpportunityCandidate, OpportunityEvidence


def test_verified_opportunity_evidence_requires_provenance() -> None:
    evidence = OpportunityEvidence(
        evidence_id="technical-tcs-2026-07-31",
        category="TECHNICAL",
        as_of_date="2026-07-31",
        source_reference="scanner-output",
        payload={"trend": "UP"},
    )
    assert evidence.category == "TECHNICAL"


def test_missing_source_reference_is_rejected() -> None:
    with pytest.raises(ValueError):
        OpportunityEvidence(
            evidence_id="bad",
            category="NEWS",
            as_of_date="2026-07-31",
            source_reference="",
        )


def test_qualified_candidate_requires_evidence() -> None:
    with pytest.raises(ValueError):
        OpportunityCandidate(
            symbol="TCS",
            generated_date="2026-07-31",
            status="QUALIFIED",
            horizon="POSITIONAL",
            confidence="HIGH",
            score=82.5,
        )


def test_insufficient_data_cannot_be_high_confidence() -> None:
    with pytest.raises(ValueError):
        OpportunityCandidate(
            symbol="INFY",
            generated_date="2026-07-31",
            status="INSUFFICIENT_DATA",
            horizon="LONG_TERM",
            confidence="HIGH",
            score=40,
        )


def test_valid_watchlist_candidate() -> None:
    candidate = OpportunityCandidate(
        symbol="RELIANCE",
        generated_date="2026-07-31",
        status="WATCHLIST",
        horizon="SWING",
        confidence="MEDIUM",
        score=68,
        evidence_ids=("technical-reliance-1",),
        rationale=("Trend improving",),
        risks=("Breakout not confirmed",),
    )
    assert candidate.score == 68
