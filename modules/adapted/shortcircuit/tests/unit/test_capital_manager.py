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


"""
Tests for capital_manager.py — funds parsing, sizing, and the capital slot.

The funds parser exists because the broker returns the same information in
several different shapes. Getting it wrong is expensive in a specific way: an
earlier revision read the "Utilized Amount" field instead of "Available
Balance", so the bot sized every position against money it had already spent.
"""

import asyncio

import pytest
from shortcircuit.capital.capital_manager import CapitalManager


@pytest.fixture
def cm():
    return CapitalManager(leverage=5.0)


# the multi-shape funds parser


def test_parses_v3_fund_limit_and_picks_available_not_utilised(cm, funds_responses):
    """
    id=10 is Available Balance; id=2 is Utilized Amount. Picking id=2 would size
    against already-committed margin.
    """
    assert cm._parse_fyers_funds(funds_responses["v3_fund_limit"]) == 4000.0


def test_parses_by_title_when_the_id_is_unfamiliar(cm, funds_responses):
    assert cm._parse_fyers_funds(funds_responses["title_only"]) == 2500.0


def test_parses_the_equity_dict_shape(cm, funds_responses):
    assert cm._parse_fyers_funds(funds_responses["equity_dict"]) == 3000.0


def test_parses_the_flat_dict_shape(cm, funds_responses):
    assert cm._parse_fyers_funds(funds_responses["flat_dict"]) == 1500.0


def test_rejects_an_error_response(cm, funds_responses):
    with pytest.raises(ValueError):
        cm._parse_fyers_funds(funds_responses["error"])


def test_rejects_a_malformed_response_rather_than_returning_zero(cm, funds_responses):
    """
    Failing loudly matters here: silently returning 0.0 would look like an empty
    account and block trading with no explanation.
    """
    with pytest.raises(ValueError):
        cm._parse_fyers_funds(funds_responses["malformed"])


def test_rejects_a_non_dict(cm):
    with pytest.raises(ValueError):
        cm._parse_fyers_funds(None)


# sizing


def test_compute_qty_returns_zero_before_the_first_sync(cm):
    """No margin known yet — must refuse to size rather than guess."""
    assert cm.compute_qty("NSE:TESTSYM-EQ", 100.0) == (0, 0.0, 0.0)


def test_compute_qty_returns_zero_for_a_non_positive_price(cm):
    cm._real_margin = 10_000.0
    assert cm.compute_qty("NSE:TESTSYM-EQ", 0.0) == (0, 0.0, 0.0)


def test_compute_qty_respects_the_safety_buffer(cm):
    """Margin required must stay within 98% of real margin (Fyers code -50 guard)."""
    cm._real_margin = 1_000.0
    qty, cost, margin_req = cm.compute_qty("NSE:TESTSYM-EQ", 100.0, 5.0)
    assert qty > 0
    assert margin_req <= cm._real_margin * 0.98


def test_compute_qty_scales_with_leverage(cm):
    cm._real_margin = 1_000.0
    qty_5x, _, _ = cm.compute_qty("NSE:TESTSYM-EQ", 100.0, 5.0)
    qty_4x, _, _ = cm.compute_qty("NSE:TESTSYM-EQ", 100.0, 4.0)
    assert qty_5x > qty_4x, "lower leverage must buy fewer shares"


def test_the_5x_to_4x_downgrade_reduces_size(cm):
    """The graceful-degradation path taken when the broker rejects 5x margin."""
    cm._real_margin = 800.0
    qty_5x, cost_5x, _ = cm.compute_qty("NSE:TESTSYM-EQ", 395.0, 5.0)
    qty_4x, cost_4x, _ = cm.compute_qty("NSE:TESTSYM-EQ", 395.0, 4.0)
    assert qty_4x < qty_5x
    assert cost_4x < cost_5x


def test_compute_qty_returns_zero_when_one_share_is_unaffordable(cm):
    cm._real_margin = 10.0
    qty, _, _ = cm.compute_qty("NSE:EXPENSIVE-EQ", 50_000.0, 5.0)
    assert qty == 0


# the capital slot


def test_slot_starts_free(cm):
    assert cm.is_slot_free is True
    assert cm.active_symbol is None


def test_acquire_marks_the_slot_occupied(cm):
    asyncio.run(cm.acquire_slot("NSE:TESTSYM-EQ"))
    assert cm.is_slot_free is False
    assert cm.active_symbol == "NSE:TESTSYM-EQ"


def test_acquiring_an_occupied_slot_raises(cm):
    """Single-position invariant. A second concurrent entry must be impossible."""
    asyncio.run(cm.acquire_slot("NSE:FIRST-EQ"))
    with pytest.raises(RuntimeError, match="occupied"):
        asyncio.run(cm.acquire_slot("NSE:SECOND-EQ"))


def test_release_frees_the_slot(cm):
    asyncio.run(cm.acquire_slot("NSE:TESTSYM-EQ"))
    asyncio.run(cm.release_slot(broker=None))
    assert cm.is_slot_free is True
    assert cm.active_symbol is None


def test_force_reset_clears_a_stuck_slot(cm):
    """
    Emergency path used by reconciliation. It exists because `is_slot_free` is a
    read-only property — assigning to it raises, which once left the slot locked
    for an entire session.
    """
    asyncio.run(cm.acquire_slot("NSE:TESTSYM-EQ"))
    cm.force_reset_slot(reason="TEST")
    assert cm.is_slot_free is True
    assert cm.active_symbol is None


def test_is_slot_free_is_read_only():
    """Documents why force_reset_slot has to exist."""
    cm = CapitalManager()
    with pytest.raises(AttributeError):
        cm.is_slot_free = True


def test_buying_power_is_margin_times_leverage(cm):
    cm._real_margin = 1_000.0
    assert cm.buying_power == 5_000.0


def test_slot_status_reports_the_active_symbol(cm):
    asyncio.run(cm.acquire_slot("NSE:TESTSYM-EQ"))
    status = cm.get_slot_status()
    assert status["slot_free"] is False
    assert status["active_symbol"] == "NSE:TESTSYM-EQ"
