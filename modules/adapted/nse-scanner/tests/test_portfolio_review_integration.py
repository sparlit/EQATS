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


"""End-to-end contract tests for Sprint 8 portfolio intelligence."""

import json
from typing import TYPE_CHECKING

from src.portfolio_review.health_builder import build_portfolio_health
from src.portfolio_review.review_repository import save_review
from src.portfolio_review.telegram_health import render_portfolio_health_message

if TYPE_CHECKING:
    from pathlib import Path


def _review(symbol: str, period: str = "2026-08") -> dict:
    return {
        "symbol": symbol,
        "review_date": "2026-08-01",
        "review_period": period,
        "technical_status": "BULLISH",
        "fundamental_status": "NOT_REVIEWED",
        "management_status": "UNKNOWN",
        "risk_status": "LOW",
        "suggested_action": "HOLD",
        "material_change": False,
        "confidence_score": 80,
        "summary": "Verified technical evidence remains constructive.",
        "key_positives": ["Daily and weekly trend alignment"],
        "key_concerns": [],
        "evidence_status": "TECHNICAL_ONLY",
        "data_limitations": ["Fundamental evidence was not supplied"],
    }


def test_review_to_health_to_telegram_end_to_end(tmp_path: Path) -> None:
    portfolio = {
        "positions": {
            "TCS": {"symbol": "TCS", "status": "OPEN", "quantity": 5, "entry_price": 3500},
            "INFY": {"symbol": "INFY", "status": "OPEN", "quantity": 4, "entry_price": 1500},
        },
        "closed": [],
    }
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    reports_root = tmp_path / "reports" / "portfolio"
    save_review(_review("TCS"), reports_root=reports_root)

    health = build_portfolio_health(portfolio_path=portfolio_path, reports_root=reports_root)
    assert health["summary"]["active_positions"] == 2
    assert health["summary"]["reviewed"] == 1
    assert health["summary"]["pending"] == 1

    by_symbol = {item["symbol"]: item for item in health["positions"]}
    assert by_symbol["TCS"]["suggested_action"] == "HOLD"
    assert by_symbol["INFY"]["suggested_action"] in {"REVIEW", "INSUFFICIENT_DATA"}

    message = render_portfolio_health_message(health)
    assert "KJ PORTFOLIO INTELLIGENCE" in message
    assert "TCS" in message
    assert "INFY" in message
    assert "stop-loss" in message.lower()


def test_corrupt_latest_review_is_not_trusted(tmp_path: Path) -> None:
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(
        json.dumps({"positions": {"TCS": {"symbol": "TCS", "status": "OPEN", "quantity": 1}}}),
        encoding="utf-8",
    )
    latest = tmp_path / "reports" / "portfolio" / "TCS" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text("{not valid json", encoding="utf-8")

    health = build_portfolio_health(portfolio_path=portfolio_path, reports_root=tmp_path / "reports" / "portfolio")
    item = health["positions"][0]
    assert item["review_status"] != "VALID"
    assert item["suggested_action"] in {"REVIEW", "INSUFFICIENT_DATA"}
