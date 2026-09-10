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


"""Tests for the named hard-gate functions in scanner.py."""
import math

import pytest
from scanner import (
    gate_corporate_actions,
    gate_drawdown,
    gate_f_score,
    gate_holdings,
    gate_liquidity_adequacy,
    gate_rsi,
    gate_surveillance,
    relative_strength_factor,
)
from settings import (
    DRAWDOWN_LOWER_PCT,
    DRAWDOWN_UPPER_PCT,
    MIN_ADV_SECONDARY_FLOOR_INR,
    MIN_ADV_VALUE_INR,
    MIN_DELIVERY_VALUE_INR,
    MIN_F_SCORE,
    MIN_HOLDINGS_CONVICTION_PCT,
    RSI_LOWER,
    RSI_UPPER,
)


def test_gate_f_score_pass():
    ok, why = gate_f_score(MIN_F_SCORE)
    assert ok
    assert why is None


def test_gate_f_score_fail():
    ok, why = gate_f_score(MIN_F_SCORE - 1)
    assert not ok
    assert why
    assert "f_score" in why


def test_gate_f_score_missing():
    ok, why = gate_f_score(None)
    assert not ok
    assert why == "f_score_missing"


def test_gate_drawdown_pass():
    ok, why = gate_drawdown(-25.0)
    assert ok
    assert why is None


def test_gate_drawdown_outside_window():
    ok, why = gate_drawdown(-10.0)
    assert not ok
    assert "outside" in why


def test_gate_drawdown_missing():
    ok, why = gate_drawdown(None)
    assert not ok
    assert why == "pct_off_high_missing"


def test_gate_rsi_pass():
    ok, why = gate_rsi(32.0)
    assert ok
    assert why is None


def test_gate_rsi_outside_window():
    ok, _why = gate_rsi(20.0)
    assert not ok


def test_gate_liquidity_pass_via_actual_delivery():
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_SECONDARY_FLOOR_INR,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR,
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert ok
    assert why is None


def test_gate_liquidity_pass_via_adv_when_delivery_thin():
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_VALUE_INR,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR - 1,
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert ok
    assert why is None


def test_gate_liquidity_pass_via_adv_when_proxy_only():
    """Single-day proxy alone must NOT satisfy the gate;