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


from datetime import date

import pytest
from app.portfolio.exits import (
    Bar,
    PositionView,
    evaluate_exit,
    stop_pct,
    target_pct,
    trail_arm_pct,
)

MAX_HOLD_DAYS = 21
FLAT_STOP_PCT = 0.07
FLAT_TARGET_PCT = 0.18
FLAT_TRAIL_ARM_PCT = 0.12

ENTRY = date(2024, 1, 1)
# Entered at 100: stop 93, target 118
BASE = PositionView(
    entry_date=ENTRY,
    stop_price=93.0,
    target_price=118.0,
)


@pytest.fixture(autouse=True)
def patch_exit_settings(monkeypatch):
    """Pin thresholds so these tests don't depend on the local .env."""
    monkeypatch.setattr("app.portfolio.exits.settings.max_hold_days", MAX_HOLD_DAYS)
    monkeypatch.setattr("app.portfolio.exits.settings.stop_loss_pct", FLAT_STOP_PCT)
    monkeypatch.setattr("app.portfolio.exits.settings.take_profit_pct", FLAT_TARGET_PCT)
    monkeypatch.setattr("app.portfolio.exits.settings.trail_activation_pct", FLAT_TRAIL_ARM_PCT)
    monkeypatch.setattr("app.portfolio.exits.settings.stop_atr_mult", 2.5)
    monkeypatch.setattr("app.portfolio.exits.settings.target_atr_mult", 4.0)
    monkeypatch.setattr("app.portfolio.exits.settings.trail_arm_atr_mult", 2.0)


def day(n: int) -> date:
    """n calendar days after entry."""
    return date.fromordinal(ENTRY.toordinal() + n)


# ── holding ───────────────────────────────────────────────────────────────────


def test_holds_when_price_sits_between_stop_and_target():
    bar = Bar(open=100.0, high=105.0, low=97.0, close=102.0)
    assert evaluate_exit(BASE, bar, day(5)) is None


# ── stop ──────────────────────────────────────────────────────────────────────


def test_stop_fires_when_low_touches_it():
    bar = Bar(open=100.0, high=101.0, low=92.0, close=95.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 93.0  # filled at the stop, not the low


def test_stop_fires_at_exactly_the_stop_price():
    # Boundary: comparison is `<=`, so touching the stop exits
    bar = Bar(open=100.0, high=100.0, low=93.0, close=99.0)
    assert evaluate_exit(BASE, bar, day(5))[1] == "stop"


def test_gap_down_fills_at_the_open_not_the_stop():
    # Opens 12% below the stop — you cannot fill at 93 when the market
    # never traded there. This is the whole reason the backtest models gaps.
    bar = Bar(open=82.0, high=84.0, low=80.0, close=81.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 82.0


# ── trail ─────────────────────────────────────────────────────────────────────


def test_active_trail_supersedes_the_entry_stop():
    pos = PositionView(**{**vars(BASE), "trail_stop": 110.0})
    bar = Bar(open=112.0, high=113.0, low=109.0, close=111.0)
    price, reason = evaluate_exit(pos, bar, day(5))
    assert reason == "trail"
    assert price == 110.0


def test_trail_not_used_when_zero():
    pos = PositionView(**{**vars(BASE), "trail_stop": 0.0})
    bar = Bar(open=100.0, high=101.0, low=92.0, close=95.0)
    assert evaluate_exit(pos, bar, day(5))[1] == "stop"


# ── target ────────────────────────────────────────────────────────────────────


def test_target_fires_when_high_reaches_it():
    bar = Bar(open=115.0, high=119.0, low=114.0, close=118.5)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "target"
    assert price == 118.0


def test_gap_up_fills_at_the_open_not_the_target():
    bar = Bar(open=125.0, high=127.0, low=124.0, close=126.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "target"
    assert price == 125.0


# ── the tie ───────────────────────────────────────────────────────────────────


def test_bar_touching_both_stop_and_target_resolves_as_stop():
    """A daily bar hides the intraday path, so the pessimistic branch wins.

    This encodes a modelling decision, not a mechanic: assuming the target
    filled first would silently inflate every backtest that follows.
    """
    bar = Bar(open=100.0, high=120.0, low=90.0, close=110.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 93.0


def test_tie_is_labelled_stop_even_when_trailing():
    """The tie branch always reports 'stop', never 'trail'."""
    pos = PositionView(**{**vars(BASE), "trail_stop": 110.0})
    bar = Bar(open=112.0, high=120.0, low=105.0, close=115.0)
    assert evaluate_exit(pos, bar, day(5))[1] == "stop"


# ── timeout ───────────────────────────────────────────────────────────────────


def test_timeout_fires_on_the_max_hold_day():
    bar = Bar(open=100.0, high=101.0, low=99.0, close=100.5)
    price, reason = evaluate_exit(BASE, bar, day(MAX_HOLD_DAYS))
    assert reason == "timeout"
    assert price == 100.5  # closes at the bar's close


def test_no_timeout_the_day_before():
    bar = Bar(open=100.0, high=101.0, low=99.0, close=100.5)
    assert evaluate_exit(BASE, bar, day(MAX_HOLD_DAYS - 1)) is None


# ── Bar.flat (the live path) ──────────────────────────────────────────────────


def test_flat_bar_triggers_stop_at_the_stop_price():
    """Live passes a single tick; the ladder must behave identically."""
    price, reason = evaluate_exit(BASE, Bar.flat(92.0), day(5))
    assert reason == "stop"
    assert price == 92.0  # min(open, stop) collapses to the observed price


def test_flat_bar_holds_between_the_levels():
    assert evaluate_exit(BASE, Bar.flat(100.0), day(5)) is None


def test_flat_bar_hits_target():
    price, reason = evaluate_exit(BASE, Bar.flat(120.0), day(5))
    assert reason == "target"
    assert price == 120.0


# ── stop and target distances ─────────────────────────────────────────────────
#
# Shared by the live risk agent and the backtest engine, which each used to
# carry their own copy of this arithmetic.


@pytest.mark.parametrize(
    ("atr_pct", "expected"),
    [
        (0.5, 0.05),  # floor
        (1.5, 0.05),  # floor — the screener's minimum ATR
        (2.0, 0.05),  # floor, exactly where it stops binding
        (2.4, 0.06),
        (3.0, 0.075),
        (4.0, 0.10),  # cap, exactly where it starts binding
        (6.0, 0.10),  # cap
    ],
)
def test_stop_distance_is_2_5x_atr_bounded_5_to_10(atr_pct, expected):
    assert stop_pct(atr_pct) == pytest.approx(expected)


def test_the_bounds_bind_below_2_and_above_4_percent_atr():
    """Worth pinning: these are the points where risk/reward stops varying
    with volatility, which is what makes an ATR-scaled target a live question."""
    assert stop_pct(1.99) == 0.05
    assert stop_pct(2.01) > 0.05
    assert stop_pct(3.99) < 0.10
    assert stop_pct(4.01) == 0.10


@pytest.mark.parametrize("missing", [None, 0.0, -1.0])
def test_missing_atr_falls_back_to_the_flat_stop(missing):
    """The two call sites guarded this differently — the engine would have
    raised on None — so the fallback lives in one place now."""
    assert stop_pct(missing) == FLAT_STOP_PCT


@pytest.mark.parametrize(
    ("atr_pct", "expected"),
    [
        (1.5, 0.06),  # floor, exactly where it stops binding
        (2.0, 0.08),
        (3.0, 0.12),
        (3.33, 0.1332),
        (5.0, 0.20),  # cap, exactly where it starts binding
        (7.0, 0.20),  # cap
    ],
)
def test_target_is_4x_atr_bounded_6_to_20(atr_pct, expected):
    """3x was measured and lost badly (+53% vs +82%); 4x won. The multiplier
    is load-bearing, so pin it."""
    assert target_pct(atr_pct) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("atr_pct", "expected"),
    [
        (1.5, 0.04),  # floor
        (3.0, 0.06),
        (3.33, 0.0666),
        (6.0, 0.12),  # cap
        (9.0, 0.12),  # cap
    ],
)
def test_trail_arms_at_2x_atr_bounded_4_to_12(atr_pct, expected):
    assert trail_arm_pct(atr_pct) == pytest.approx(expected)


@pytest.mark.parametrize("atr_pct", [1.5, 2.0, 3.0, 3.33, 4.0, 5.0, 6.0, 8.0, 12.0])
def test_the_trail_always_arms_below_the_target(atr_pct):
    """The invariant the whole ladder rests on.

    A flat 12% arming point against an ATR-scaled target sits *above* the
    target sits above the target on most stocks, so the trail would never arm.
    """
    assert trail_arm_pct(atr_pct) < target_pct(atr_pct)


@pytest.mark.parametrize("missing", [None, 0.0, -1.0])
def test_missing_atr_falls_back_to_the_flat_ladder(missing):
    assert target_pct(missing) == FLAT_TARGET_PCT
    assert trail_arm_pct(missing) == FLAT_TRAIL_ARM_PCT


def test_reward_to_risk_is_now_roughly_constant():
    """The ATR cancels between a 4x target and a 2.5x stop, so risk/reward no
    longer varies with volatility — which is why the scoring dimension built on
    it can no longer discriminate between candidates."""
    mid = target_pct(3.0) / stop_pct(3.0)
    high = target_pct(4.0) / stop_pct(4.0)

    assert mid == pytest.approx(1.6)
    assert high == pytest.approx(1.6)
