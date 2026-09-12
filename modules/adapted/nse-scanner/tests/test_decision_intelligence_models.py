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
from src.decision_intelligence.models import DecisionInput, DecisionRecommendation


def test_valid_ready_decision() -> None:
    item = DecisionRecommendation(
        decision_id="decision-tcs-2026-07-31",
        generated_date="2026-07-31",
        status="READY",
        action="HOLD",
        confidence="HIGH",
        score=78.5,
        rationale=("Company quality and technical evidence remain supportive",),
        evidence_references=("company:TCS:latest", "technical:TCS:daily"),
        component_scores={"company": 82.0, "technical": 75.0},
    )
    assert item.action == "HOLD"


def test_ready_decision_requires_evidence() -> None:
    with pytest.raises(ValueError):
        DecisionRecommendation(
            decision_id="missing-evidence",
            generated_date="2026-07-31",
            status="READY",
            action="HOLD",
            confidence="MEDIUM",
            score=60,
            rationale=("Unsupported",),
        )


def test_insufficient_data_cannot_recommend_buy() -> None:
    with pytest.raises(ValueError):
        DecisionRecommendation(
            decision_id="unsafe-buy",
            generated_date="2026-07-31",
            status="INSUFFICIENT_DATA",
            action="BUY",
            confidence="LOW",
            limitations=("Financial evidence missing",),
        )


def test_component_score_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        DecisionRecommendation(
            decision_id="bad-score",
            generated_date="2026-07-31",
            status="PARTIAL",
            action="WATCH",
            confidence="LOW",
            component_scores={"market": 101},
        )


def test_decision_input_rejects_duplicate_evidence() -> None:
    with pytest.raises(ValueError):
        DecisionInput(
            decision_id="duplicate",
            scope="COMPANY",
            as_of_date="2026-07-31",
            subject="INFY",
            evidence_references=("company:INFY:latest", "company:INFY:latest"),
        )
