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


import pandas as pd
from pine_hull.opportunity_lifecycle import timing_state as pine_timing_state
from v2.opportunity_lifecycle import entry_horizon, timing_state


def test_v2_daily_ready_weekly_improving_is_early() -> None:
    assert (
        timing_state(
            classification="WATCH",
            metrics={"daily_bullish": True, "kama_rising": True, "stretched": False},
            htf_state="IMPROVING",
            trade_plan_state="WAIT",
            reward_risk_t1=1.5,
            pullback_state="NO_PULLBACK",
        )
        == "EARLY"
    )


def test_v2_action_with_valid_plan_is_ready() -> None:
    assert (
        timing_state(
            classification="ACTION",
            metrics={"daily_bullish": True, "kama_rising": True, "stretched": False},
            htf_state="BULLISH",
            trade_plan_state="READY",
            reward_risk_t1=1.5,
            pullback_state="NO_PULLBACK",
        )
        == "READY"
    )


def test_v2_extended_overrides_confirmation() -> None:
    assert (
        timing_state(
            classification="WATCH",
            metrics={"daily_bullish": True, "kama_rising": True, "stretched": True},
            htf_state="BULLISH",
            trade_plan_state="WAIT",
            reward_risk_t1=0.8,
            pullback_state="NO_PULLBACK",
        )
        == "EXTENDED"
    )


def test_entry_horizon_separates_execution_from_quality() -> None:
    assert entry_horizon("6M", "TREND_CONTINUATION") == "3M"
    assert entry_horizon("12M", "HULL_CROSSOVER") == "1M"
    assert entry_horizon("1M", "TREND_CONTINUATION") == "1M"


def test_pine_daily_ready_with_improving_weekly_is_early() -> None:
    assert (
        pine_timing_state(
            daily_bullish=True,
            hma_aligned=True,
            kama_rising=True,
            trend_commitment=True,
            chop=False,
            rotational=False,
            overextended=False,
            score=80,
            htf_state="IMPROVING",
        )
        == "EARLY"
    )


def test_pine_full_alignment_is_ready() -> None:
    assert (
        pine_timing_state(
            daily_bullish=True,
            hma_aligned=True,
            kama_rising=True,
            trend_commitment=True,
            chop=False,
            rotational=False,
            overextended=False,
            score=80,
            htf_state="BULLISH",
        )
        == "READY"
    )


def test_pine_kama_is_diagnostic_not_a_ready_gate() -> None:
    assert (
        pine_timing_state(
            daily_bullish=True,
            daily_persistent=True,
            hma_aligned=True,
            kama_rising=False,
            trend_commitment=True,
            adx_confirmed=True,
            chop=False,
            rotational=False,
            overextended=False,
            score=80,
            htf_state="BULLISH",
        )
        == "READY"
    )


def test_pine_overextended_is_not_ready() -> None:
    assert (
        pine_timing_state(
            daily_bullish=True,
            hma_aligned=True,
            kama_rising=True,
            trend_commitment=True,
            chop=False,
            rotational=False,
            overextended=True,
            score=90,
            htf_state="BULLISH",
        )
        == "EXTENDED"
    )
