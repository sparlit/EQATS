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


import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DATA_ROOT = Path(os.getenv("OPTION_WORKSTATION_DATA_ROOT", "data")).expanduser()
pytestmark = pytest.mark.integration

if not (DATA_ROOT / "underlying" / "symbol=SPY").is_dir():
    pytest.skip(
        "licensed ThetaData fixture is not available; set OPTION_WORKSTATION_DATA_ROOT",
        allow_module_level=True,
    )

from backend.app import app

client = TestClient(app)


def test_catalog_and_session_expose_replay_timeline() -> None:
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert "SPY" in catalog.json()["symbols"]
    assert "2026-07-10" in catalog.json()["common_dates"]

    session = client.get("/api/session?symbols=SPY,QQQ&date=2026-07-10")
    assert session.status_code == 200
    payload = session.json()
    assert payload["timeline"][0] == "09:30"
    assert payload["timeline"][-1] == "16:00"
    assert len(payload["series"]["SPY"]["bars"]) == 391


def test_chain_computes_smile_greeks_and_gex() -> None:
    response = client.get("/api/chain?symbol=SPY&date=2026-07-10&minute=10:30&expiration=2026-07-10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["spot"] > 0
    assert payload["metrics"]["contracts"] > 100
    assert payload["snapshot_id"]
    assert payload["provenance"]["model"] == "BSM+SVI-v1"
    assert payload["metrics"]["rr25"] is not None
    assert payload["metrics"]["gamma_flip"] is not None
    assert payload["quality"]["usable_pct"] > 0
    assert payload["gex_by_strike"]
    assert all(0 < row["iv"] <= 400 for row in payload["rows"])
    assert all("quality_score" in row and "vanna" in row and "charm" in row for row in payload["rows"])
    assert {row["right"] for row in payload["rows"]} == {"CALL", "PUT"}


def test_surface_samples_multiple_expirations() -> None:
    response = client.get("/api/surface?symbol=SPY&date=2026-07-10&minute=10:30&max_dte=60")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["term"]) >= 3
    assert len(payload["points"]) >= 100
    assert len(payload["grid"]) >= 3
    assert all(len(row) == 25 for row in payload["grid"])
    assert all(len(cell) == 3 for row in payload["grid"] for cell in row)
    assert all(0.75 <= point["moneyness"] <= 1.25 for point in payload["points"])
    assert "calendar_violations" in payload["arbitrage"]
    assert payload["arbitrage"]["post_projection_calendar_violations"] == 0
    assert payload["arbitrage"]["post_projection_convexity_violations"] == 0
    assert all("net_gex" in point for point in payload["term"])


def test_volatility_context_contains_rv_rank_and_expected_move() -> None:
    response = client.get("/api/volatility-context?symbol=SPY&date=2026-07-10&minute=10:30&expiration=2026-07-17")
    assert response.status_code == 200
    payload = response.json()
    assert payload["expected_move"] > 0
    assert payload["realized_volatility"]["20"] > 0
    assert 0 <= payload["iv_rank"] <= 100
    assert payload["history"]
