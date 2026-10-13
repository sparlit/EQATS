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
The restored exit policy.

Three exits were removed within six days of each other in August 2026:

    f6eae88  6 Aug   take-profit engine deleted, MAX_HOLD_TIME_MINUTES 45 -> 0
    90a2998 12 Aug   VWAP anchor moved from a rolling window to the session open

The 31 LIVE trades before that scored +5.56%; the 15 after scored -3.42%.
Replaying all 46 on real 1-minute candles from the Fyers history API put every
restored policy ahead of "stop-loss and EOD only", so all three came back on
2026-08-30 behind config switches.

These tests pin the *decisions*, not the plumbing: which level closes a trade,
which side of entry a target has to be on, and how many bars the VWAP anchor is
computed over. The paired confidence intervals in that replay all span zero, so
the policy choice is a bet — but it should be the bet the config says it is.
"""

import pytest
from shortcircuit.execution.focus_engine import compute_tp_levels, target_reached

# which side of entry counts as "reached"


@pytest.mark.parametrize(
    "ltp,level,direction,expected",
    [
        (99.0, 100.0, "SHORT", True),  # short target sits below entry
        (100.0, 100.0, "SHORT", True),  # touching the level is reaching it
        (101.0, 100.0, "SHORT", False),
        (101.0, 100.0, "LONG", True),  # long target sits above entry
        (100.0, 100.0, "LONG", True),
        (99.0, 100.0, "LONG", False),
    ],
)
def test_direction_decides_which_way_a_target_is_reached(ltp, level, direction, expected):
    assert target_reached(ltp, level, direction) is expected


def test_a_missing_level_is_never_reached():
    """
    TP_MODE='OFF' and the wrong-side guard both produce None. If None ever read
    as 'reached', every position would close on its first tick.
    """
    assert target_reached(100.0, None, "SHORT") is False
    assert target_reached(100.0, None, "LONG") is False


def test_no_price_is_not_a_reason_to_exit():
    """A cache miss returns 0. Exiting on it would close at an unknown price."""
    assert target_reached(0, 100.0, "SHORT") is False


# the two levels


def test_the_midpoint_sits_halfway_between_entry_and_the_vwap_target():
    tp_1, tp_2 = compute_tp_levels(entry_price=100.0, vwap_target=90.0, tick=0.05, is_long=False)
    assert tp_2 == pytest.approx(90.0)
    assert tp_1 == pytest.approx(95.0)


def test_both_levels_land_on_the_instruments_tick():
    """
    NSE revised its tick bands in 2025 and they are per-symbol: TIINDIA and SBIN
    are 0.10, CAMLINFINE is 0.01. A target off-tick is rejected by the broker.
    """
    tp_1, tp_2 = compute_tp_levels(
        entry_price=2992.85, vwap_target=2871.33, tick=0.10, is_long=False
    )
    for level in (tp_1, tp_2):
        assert round(level / 0.10) == pytest.approx(level / 0.10, abs=1e-9)


def test_a_long_midpoint_is_above_entry():
    tp_1, tp_2 = compute_tp_levels(entry_price=100.0, vwap_target=110.0, tick=0.05, is_long=True)
    assert tp_2 == pytest.approx(110.0)
    assert tp_1 == pytest.approx(105.0)


# the guard that stops a trade closing on its own first tick


@pytest.mark.parametrize(
    "entry,target,is_long,why",
    [
        (100.0, 100.0, False, "target equal to entry"),
        (100.0, 105.0, False, "short target ABOVE entry — VWAP already crossed"),
        (100.0, 100.0, True, "target equal to entry"),
        (100.0, 95.0, True, "long target BELOW entry"),
    ],
)
def test_a_target_not_beyond_entry_is_refused(entry, target, is_long, why):
    """
    If VWAP has already been crossed when the fill lands, the target is behind
    price. Trading it would exit instantly at a loss; the trade must instead run
    on its stop.
    """
    assert compute_tp_levels(entry, target, 0.05, is_long) == (None, None), why


@pytest.mark.parametrize("entry,target", [(0, 90.0), (-5, 90.0), (100.0, None)])
def test_unusable_inputs_produce_no_target(entry, target):
    assert compute_tp_levels(entry, target, 0.05, False) == (None, None)


def test_a_nonsense_tick_does_not_divide_by_zero():
    tp_1, tp_2 = compute_tp_levels(100.0, 90.0, 0.0, False)
    assert tp_1 is not None and tp_2 is not None


# the policies these levels implement


def test_single_closes_at_the_midpoint_and_scale_does_not():
    """
    The difference between the two restored modes, stated once. SINGLE exits
    100% at tp_1; SCALE takes half there and needs tp_2 for the remainder.
    """
    tp_1, tp_2 = compute_tp_levels(100.0, 90.0, 0.05, False)
    price_at_midpoint = tp_1

    assert target_reached(price_at_midpoint, tp_1, "SHORT") is True
    assert target_reached(price_at_midpoint, tp_2, "SHORT") is False


def test_the_vwap_target_closes_the_remainder():
    tp_1, tp_2 = compute_tp_levels(100.0, 90.0, 0.05, False)
    assert target_reached(tp_2, tp_2, "SHORT") is True


def test_a_gap_through_both_levels_reaches_both():
    """
    The condition behind the ordering in focus_loop. A fast mover can clear the
    midpoint and the VWAP target inside one 5Hz tick, so both branches are live
    on the same pass.

    The loop therefore tests the FULL-exit level first and returns. Taking the
    partial first would dispatch partial_exit(half) and safe_exit(remaining)
    together — for a short both are BUYs, so 1.5x gets bought and the position
    flips net long. Order is the whole guard; there is no lock.
    """
    tp_1, tp_2 = compute_tp_levels(100.0, 90.0, 0.05, False)
    gap_price = tp_2 - 1.0

    assert target_reached(gap_price, tp_1, "SHORT") is True
    assert target_reached(gap_price, tp_2, "SHORT") is True


# the VWAP anchor the profitable run was measured on


def test_rolling_and_session_request_different_bar_counts():
    """
    features.enrich_dataframe computes a cumulative VWAP over whatever frame it
    receives, so the number of bars requested IS the anchor. These two must not
    quietly converge.
    """
    from shortcircuit import config
    from shortcircuit.execution.analyzer import SESSION_BARS_1M

    rolling = int(getattr(config, "VWAP_ROLLING_BARS", 100))
    assert rolling < SESSION_BARS_1M, "a rolling anchor must be shorter than the session"
    assert SESSION_BARS_1M >= 375, "a session anchor must cover 09:15-15:30"


def test_the_anchor_mode_is_one_of_the_two_supported_values():
    from shortcircuit import config

    assert str(getattr(config, "VWAP_ANCHOR_MODE", "SESSION")).upper() in {"ROLLING", "SESSION"}


def test_tp_mode_is_one_of_the_three_supported_values():
    from shortcircuit import config

    assert str(getattr(config, "TP_MODE", "OFF")).upper() in {"SCALE", "SINGLE", "OFF"}
