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


from dataclasses import dataclass

from src.portfolio_review.providers.base import LLMProvider, ProviderError, ProviderResponse
from src.portfolio_review.review_runner import run_review

VALID_REVIEW = {
    "symbol": "TCS",
    "review_date": "2026-08-01",
    "review_period": "2026-08",
    "technical_status": "BULLISH",
    "fundamental_status": "NOT_REVIEWED",
    "management_status": "UNKNOWN",
    "risk_status": "MEDIUM",
    "suggested_action": "HOLD",
    "material_change": False,
    "confidence_score": 70,
    "summary": "Technical trend remains constructive; fundamentals were not reviewed.",
    "key_positives": ["Trend remains aligned"],
    "key_concerns": ["Fundamental evidence unavailable"],
    "evidence_status": "TECHNICAL_ONLY",
    "data_limitations": ["Quarterly financial statements were not supplied"],
}


class FailingProvider(LLMProvider):
    name = "failing"
    model = "test"

    def generate_review(self, prompt: str) -> ProviderResponse:
        msg = "temporary provider failure"
        raise ProviderError(msg)


class SuccessfulProvider(LLMProvider):
    name = "working"
    model = "test-model"

    def generate_review(self, prompt: str) -> ProviderResponse:
        return ProviderResponse(dict(VALID_REVIEW), self.name, self.model)


def test_runner_falls_back_and_saves_valid_review(tmp_path):
    scanner = tmp_path / "scanner.json"
    scanner.write_text('{"stocks":[{"symbol":"TCS","close":4000,"rsi":60}]}', encoding="utf-8")

    def builder(name: str) -> LLMProvider:
        return FailingProvider() if name == "primary" else SuccessfulProvider()

    result = run_review(
        {"symbol": "TCS", "position": {"entry_price": 3800, "quantity": 1}},
        "2026-08",
        scanner_path=scanner,
        reports_root=tmp_path / "reports",
        primary_provider="primary",
        fallback_provider="fallback",
        max_retries=0,
        provider_builder=builder,
    )

    assert result.status == "SUCCESS"
    assert result.provider == "working"
    assert (tmp_path / "reports" / "TCS" / "2026-08.json").exists()
    assert (tmp_path / "reports" / "TCS" / "latest.json").exists()


def test_runner_rejects_invalid_provider_payload(tmp_path):
    class InvalidProvider(LLMProvider):
        name = "invalid"
        model = "test"

        def generate_review(self, prompt: str) -> ProviderResponse:
            payload = dict(VALID_REVIEW)
            payload["fundamental_status"] = "HEALTHY"
            return ProviderResponse(payload, self.name, self.model)

    result = run_review(
        {"symbol": "TCS", "position": {}},
        "2026-08",
        scanner_path=tmp_path / "missing.json",
        reports_root=tmp_path / "reports",
        primary_provider="invalid",
        fallback_provider="invalid",
        max_retries=0,
        provider_builder=lambda _: InvalidProvider(),
    )

    assert result.status == "FAILED"
    assert "fundamental_status=NOT_REVIEWED" in result.error
