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


"""Strict validation and cross-field safety rules for LLM review output."""


from datetime import date
from typing import Any

from .models import (
    ACTIONS,
    EVIDENCE_STATUSES,
    FUNDAMENTAL_STATUSES,
    MANAGEMENT_STATUSES,
    RISK_STATUSES,
    TECHNICAL_STATUSES,
)

REQUIRED_FIELDS = {
    "symbol",
    "review_date",
    "review_period",
    "technical_status",
    "fundamental_status",
    "management_status",
    "risk_status",
    "suggested_action",
    "material_change",
    "confidence_score",
    "summary",
    "key_positives",
    "key_concerns",
    "evidence_status",
    "data_limitations",
}


def validate_review(review: dict[str, Any], expected_symbol: str | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(review, dict):
        return ["Review must be a JSON object"]

    missing = sorted(REQUIRED_FIELDS - set(review))
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}")
        return errors

    symbol = str(review.get("symbol", "")).strip().upper()
    if expected_symbol and symbol != expected_symbol.strip().upper():
        errors.append("Review symbol does not match requested symbol")

    try:
        date.fromisoformat(str(review.get("review_date")))
    except ValueError:
        errors.append("review_date must be YYYY-MM-DD")

    period = str(review.get("review_period", ""))
    if len(period) != 7 or period[4:5] != "-" or not period[:4].isdigit() or not period[5:].isdigit():
        errors.append("review_period must be YYYY-MM")
    elif not 1 <= int(period[5:]) <= 12:
        errors.append("review_period month must be between 01 and 12")

    enum_checks = (
        ("technical_status", TECHNICAL_STATUSES),
        ("fundamental_status", FUNDAMENTAL_STATUSES),
        ("management_status", MANAGEMENT_STATUSES),
        ("risk_status", RISK_STATUSES),
        ("suggested_action", ACTIONS),
        ("evidence_status", EVIDENCE_STATUSES),
    )
    for field, allowed in enum_checks:
        if review.get(field) not in allowed:
            errors.append(f"Unsupported {field}: {review.get(field)!r}")

    score = review.get("confidence_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        errors.append("confidence_score must be numeric between 0 and 100")

    if not isinstance(review.get("material_change"), bool):
        errors.append("material_change must be boolean")
    if not isinstance(review.get("summary"), str) or not review["summary"].strip():
        errors.append("summary must be a non-empty string")
    for field in ("key_positives", "key_concerns", "data_limitations"):
        value = review.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{field} must be a list of strings")

    evidence_status = review.get("evidence_status")
    if evidence_status in {"TECHNICAL_ONLY", "FAILED"}:
        if review.get("fundamental_status") != "NOT_REVIEWED":
            errors.append("Technical-only/failed evidence requires fundamental_status=NOT_REVIEWED")
        if review.get("management_status") != "UNKNOWN":
            errors.append("Technical-only/failed evidence requires management_status=UNKNOWN")

    if evidence_status == "FAILED" and review.get("suggested_action") not in {"REVIEW", "INSUFFICIENT_DATA"}:
        errors.append("Failed evidence permits only REVIEW or INSUFFICIENT_DATA")

    return errors


def assert_valid_review(review: dict[str, Any], expected_symbol: str | None = None) -> None:
    errors = validate_review(review, expected_symbol)
    if errors:
        raise ValueError("; ".join(errors))
