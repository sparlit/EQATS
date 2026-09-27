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
from src.ai_research_assistant.models import ResearchAnswer, ResearchQuery


def test_query_normalizes_symbols() -> None:
    query = ResearchQuery(
        query_id="q-1",
        question="Compare TCS and Infosys",
        query_type="COMPARISON",
        requested_date="2026-07-31",
        symbols=(" tcs ", "infy"),
    )
    assert query.symbols == ("TCS", "INFY")


def test_ready_answer_requires_evidence() -> None:
    with pytest.raises(ValueError):
        ResearchAnswer(
            query_id="q-1",
            generated_date="2026-07-31",
            status="READY",
            confidence="HIGH",
            summary="Evidence-backed comparison",
        )


def test_insufficient_data_cannot_claim_high_confidence() -> None:
    with pytest.raises(ValueError):
        ResearchAnswer(
            query_id="q-2",
            generated_date="2026-07-31",
            status="INSUFFICIENT_DATA",
            confidence="HIGH",
            summary="Not enough verified evidence",
            limitations=("Financial evidence missing",),
        )


def test_ready_answer_with_evidence() -> None:
    answer = ResearchAnswer(
        query_id="q-3",
        generated_date="2026-07-31",
        status="READY",
        confidence="MEDIUM",
        summary="Technical and company evidence support the conclusion.",
        evidence_references=("company:TCS:latest", "market:2026-07-31"),
    )
    assert answer.status == "READY"
