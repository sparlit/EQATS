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


import json
from pathlib import Path

import pytest
from src.portfolio_review import (
    build_review_prompt,
    collect_evidence,
    load_latest_review,
    save_review,
    validate_review,
)
from src.portfolio_review.review_repository import ReviewAlreadyExistsError


def _valid_review(symbol="TCS", evidence_status="TECHNICAL_ONLY"):
    return {
        "symbol": symbol,
        "review_date": "2026-08-01",
        "review_period": "2026-08",
        "technical_status": "BULLISH",
        "fundamental_status": "NOT_REVIEWED",
        "management_status": "UNKNOWN",
        "risk_status": "MEDIUM",
        "suggested_action": "HOLD",
        "material_change": False,
        "confidence_score": 70,
        "summary": "The technical position remains valid based on supplied evidence.",
        "key_positives": ["Trend remains aligned"],
        "key_concerns": ["Fundamentals were not verified"],
        "evidence_status": evidence_status,
        "data_limitations": ["Quarterly statements were not supplied"],
    }


def test_collect_evidence_is_explicit_when_scanner_data_missing(tmp_path):
    item = {"symbol": "TCS", "position": {"entry_price": 100}}
    evidence = collect_evidence(item, tmp_path / "missing.json")
    assert evidence["evidence_status"] == "FAILED"
    assert evidence["fundamentals"] == {}
    assert evidence["data_limitations"]


def test_collect_evidence_reads_matching_stock(tmp_path):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({"stocks": [{"symbol": "TCS", "close": 120, "rsi": 61}]}))
    evidence = collect_evidence({"symbol": "TCS", "position": {}}, scan)
    assert evidence["evidence_status"] == "TECHNICAL_ONLY"
    assert evidence["technical"]["close"] == 120


def test_prompt_forbids_unverified_fundamentals():
    evidence = {"symbol": "TCS", "evidence_status": "TECHNICAL_ONLY", "data_limitations": []}
    prompt = build_review_prompt(evidence, "2026-08")
    assert "fundamental_status to NOT_REVIEWED" in prompt
    assert "Return one JSON object only" in prompt


def test_validator_rejects_fundamental_claim_without_evidence():
    review = _valid_review()
    review["fundamental_status"] = "HEALTHY"
    errors = validate_review(review, "TCS")
    assert any("fundamental_status=NOT_REVIEWED" in error for error in errors)


def test_repository_preserves_monthly_history(tmp_path):
    review = _valid_review()
    dated, latest = save_review(review, tmp_path)
    assert dated.exists()
    assert latest.exists()
    assert load_latest_review("TCS", tmp_path)["review_period"] == "2026-08"
    with pytest.raises(ReviewAlreadyExistsError):
        save_review(review, tmp_path)
