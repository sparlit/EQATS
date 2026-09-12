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

from src.portfolio_review.health_builder import build_portfolio_health, save_portfolio_health
from src.portfolio_review.telegram_health import render_portfolio_health_message


def _valid_review(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "review_date": "2026-08-01",
        "review_period": "2026-08",
        "technical_status": "BULLISH",
        "fundamental_status": "NOT_REVIEWED",
        "management_status": "UNKNOWN",
        "risk_status": "LOW",
        "suggested_action": "HOLD",
        "material_change": False,
        "confidence_score": 78,
        "summary": "Technical evidence remains constructive.",
        "key_positives": ["Daily and weekly trend aligned"],
        "key_concerns": [],
        "evidence_status": "TECHNICAL_ONLY",
        "data_limitations": ["Quarterly financial statements were not supplied"],
    }


def test_build_health_includes_reviewed_and_pending_positions(tmp_path: Path):
    portfolio = {
        "positions": {
            "TCS": {"status": "OPEN", "entry_price": 3500},
            "INFY": {"status": "OPEN", "entry_price": 1400},
            "OLD": {"status": "CLOSED"},
        }
    }
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")

    reports = tmp_path / "reports"
    tcs_dir = reports / "TCS"
    tcs_dir.mkdir(parents=True)
    (tcs_dir / "latest.json").write_text(json.dumps(_valid_review("TCS")), encoding="utf-8")

    health = build_portfolio_health(portfolio_path, reports)

    assert health["position_count"] == 2
    assert health["reviewed_count"] == 1
    assert health["pending_count"] == 1
    assert [row["symbol"] for row in health["positions"]] == ["INFY", "TCS"]
    assert health["positions"][0]["suggested_action"] == "INSUFFICIENT_DATA"


def test_invalid_latest_review_is_not_exposed_as_valid(tmp_path: Path):
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps({"positions": {"TCS": {"status": "OPEN"}}}), encoding="utf-8")
    reports = tmp_path / "reports" / "TCS"
    reports.mkdir(parents=True)
    invalid = _valid_review("WRONG")
    (reports / "latest.json").write_text(json.dumps(invalid), encoding="utf-8")

    health = build_portfolio_health(portfolio_path, tmp_path / "reports")

    assert health["reviewed_count"] == 0
    assert health["positions"][0]["suggested_action"] == "REVIEW"
    assert "validation_errors" in health["positions"][0]


def test_health_save_and_telegram_message(tmp_path: Path):
    health = {
        "generated_date": "2026-08-01",
        "position_count": 1,
        "reviewed_count": 1,
        "pending_count": 0,
        "action_counts": {"HOLD": 1},
        "positions": [
            {
                "symbol": "TCS",
                "review_available": True,
                "technical_status": "BULLISH",
                "fundamental_status": "NOT_REVIEWED",
                "risk_status": "LOW",
                "suggested_action": "HOLD",
                "review_date": "2026-08-01",
                "review_period": "2026-08",
                "confidence_score": 78,
                "summary": "Technical evidence remains constructive.",
            }
        ],
    }
    output = save_portfolio_health(health, tmp_path / "health.json")
    message = render_portfolio_health_message(health)

    assert output.exists()
    assert "KJ PORTFOLIO INTELLIGENCE" in message
    assert "TCS" in message
    assert "Action: HOLD" in message
    assert "stop-loss rules remain authoritative" in message
