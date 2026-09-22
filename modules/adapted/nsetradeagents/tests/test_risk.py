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
from app.agents.risk import run_risk_check

DEFAULTS = {
    "max_positions": 4,
    "starting_capital": 100000,
    "max_position_pct": 0.25,
    "stop_loss_pct": 0.07,
    "take_profit_pct": 0.18,
}


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    for key, value in DEFAULTS.items():
        monkeypatch.setattr(f"app.agents.risk.settings.{key}", value)


def test_approved_happy_path():
    result = run_risk_check(
        ticker="TITAN.NS",
        current_price=500.0,
        portfolio_cash=80000,
        open_positions=2,
    )

    assert result["approved"] is True
    assert result["quantity"] == 50  # 25000 / 500
    assert result["stop_loss"] == 465.0  # 500 * (1 - 0.07)
    assert result["take_profit"] == 590.0  # 500 * (1 + 0.18)
    assert result["block_reasons"] == []


def test_blocked_max_positions():
    result = run_risk_check(
        ticker="TITAN.NS",
        current_price=500.0,
        portfolio_cash=80000,
        open_positions=4,  # At max positions
    )

    assert result["approved"] is False
    assert any("max positions" in reason for reason in result["block_reasons"])


def test_blocked_price_too_high():
    result = run_risk_check(
        ticker="TITAN.NS",
        current_price=30000.0,  # Exceeds max_positioN_value of 25000
        portfolio_cash=80000,
        open_positions=2,
    )

    assert result["approved"] is False
    assert any("exceeds max position size" in reason for reason in result["block_reasons"])


def test_blocked_invalid_price():
    result = run_risk_check(
        ticker="TITAN.NS",
        current_price=-0,  # Invalid price
        portfolio_cash=80000,
        open_positions=2,
    )

    assert result["approved"] is False
    assert len(result["block_reasons"]) > 0


def test_approved_boundary_positions():
    result = run_risk_check(
        ticker="TITAN.NS",
        current_price=500.0,
        portfolio_cash=80000,
        open_positions=3,  # One less than max positions
    )

    assert result["approved"] is True
