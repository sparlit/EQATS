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

import numpy as np
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
    """Single-day proxy alone must NOT satisfy the gate; ADV does."""
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_VALUE_INR,
        delivery_value_inr=1_000_000_000,  # would have passed old proxy gate
        delivery_kind="traded_value_proxy",
        delivery_status="ok",
    )
    assert ok
    assert why is None


def test_gate_liquidity_proxy_only_fails():
    """Proxy without sufficient ADV must fail (was the source of the false PASSes)."""
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_VALUE_INR - 1,
        delivery_value_inr=1_000_000_000,
        delivery_kind="traded_value_proxy",
        delivery_status="ok",
    )
    assert not ok
    assert "adv" in why


def test_gate_liquidity_actual_too_low_and_adv_missing_fails():
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=None,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR - 1,
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert not ok
    assert "liquidity_missing" in why


def test_gate_liquidity_adv_below_floor_with_real_delivery_above_passes():
    """If real delivery ≥ ₹5cr, the actual path passes even when ADV is low."""
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_VALUE_INR - 1,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR,
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert ok
    assert why is None


def test_gate_liquidity_adv_below_floor_fails():
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_VALUE_INR - 1,
        delivery_value_inr=None,
        delivery_kind=None,
        delivery_status="source_failed",
    )
    assert not ok
    assert "adv" in why


def test_gate_liquidity_delivery_path_requires_secondary_adv_floor():
    """A thinly-traded name with a single high-delivery day must NOT pass."""
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=MIN_ADV_SECONDARY_FLOOR_INR - 1,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR,  # real delivery satisfies primary
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert not ok
    assert "secondary" in why


def test_gate_liquidity_delivery_path_missing_adv_fails():
    """Delivery path needs ADV for the secondary floor; ADV must not be None."""
    ok, why = gate_liquidity_adequacy(
        adv_value_inr=None,
        delivery_value_inr=MIN_DELIVERY_VALUE_INR,
        delivery_kind="actual",
        delivery_status="ok",
    )
    assert not ok
    assert "liquidity_missing" in why


def test_gate_liquidity_lenient_not_a_parameter():
    """--lenient-external-gates must NOT loosen the liquidity gate by design.

    The new gate signature intentionally drops the `lenient` kwarg: the 20d
    ADV path makes the gate reliable even when bhavcopy is unreachable,
    so there is no source-failure case to relax. Pin the contract here.
    """
    import inspect

    sig = inspect.signature(gate_liquidity_adequacy)
    assert "lenient" not in sig.parameters


def test_gate_surveillance_clean():
    ok, why = gate_surveillance(False, "ok")
    assert ok
    assert why is None


def test_gate_surveillance_restricted():
    ok, why = gate_surveillance(True, "ok")
    assert not ok
    assert why == "t_group_or_suspended"


def test_gate_surveillance_flag_only_passes():
    # flag_only means we couldn't confirm, not that we know it's restricted
    ok, why = gate_surveillance(False, "flag_only")
    assert ok
    assert why is None


def test_gate_holdings_pass():
    ok, why = gate_holdings({"conviction_pct": 70.0}, "ok")
    assert ok
    assert why is None


def test_gate_holdings_too_low():
    ok, _why = gate_holdings({"conviction_pct": MIN_HOLDINGS_CONVICTION_PCT}, "ok")
    assert not ok


def test_gate_holdings_source_failed_fails_closed():
    ok, _why = gate_holdings({"conviction_pct": 80.0}, "source_failed")
    assert not ok


def test_gate_holdings_source_failed_lenient_passes():
    ok, why = gate_holdings({"conviction_pct": 80.0}, "source_failed", lenient=True)
    assert ok
    assert why is None


def test_gate_holdings_missing_lenient_passes():
    ok, why = gate_holdings(None, "missing", lenient=True)
    assert ok
    assert why is None


def test_gate_holdings_strict_still_rejects_low_conviction_in_lenient_mode():
    """Lenient mode does NOT relax the actual >50% conviction check; only the missing-source case."""
    ok, why = gate_holdings({"conviction_pct": 30.0}, "ok", lenient=True)
    assert not ok
    assert "conviction" in why


def test_gate_corporate_actions_no_action():
    ok, why = gate_corporate_actions({"has_excluded_action": False, "actions": []})
    assert ok
    assert why is None


def test_gate_corporate_actions_excluded():
    ok, why = gate_corporate_actions({"has_excluded_action": True, "actions": [{"action": "BONUS 2:1"}]})
    assert not ok
    assert "BONUS" in why


def test_gate_corporate_actions_source_failed_passes():
    # If we couldn't fetch, we don't claim to have screened it
    ok, why = gate_corporate_actions(None)
    assert ok
    assert why is None


def test_relative_strength_penalty():
    # Stock much weaker than index -> penalty
    f = relative_strength_factor(-25.0, -5.0)
    assert f < 0.9


def test_relative_strength_bonus():
    # Index correcting and stock tracking it
    f = relative_strength_factor(-7.0, -8.0)
    assert f >= 1.0


def test_relative_strength_neutral_when_missing():
    assert relative_strength_factor(None, -5.0) == 1.0
    assert relative_strength_factor(-5.0, None) == 1.0
