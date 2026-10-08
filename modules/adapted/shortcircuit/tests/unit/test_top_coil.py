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
TopCoilShort: the coil-at-the-high detector.

It reports a coil and a trigger level; it does NOT report a break. The engine's
validation gate watches that level at 5Hz and enters intrabar. That split is
pinned here because both halves of it were wrong before they were right:

  * qualifying the coil and testing the break on the same window found 0 setups
    in 997 stock-days — the breaking bar widens the range, so the window fails
    its own tightness test;
  * a later version waited for a 1-minute bar to CLOSE below the coil. It scored
    -0.302% per trade against -0.070% for entering at the level, because by the
    close price is already through it and the stop is 0.14pp wider;
  * and an earlier measurement showed +0.091% only because it filled at the break
    level while triggering on a close. Honest fills erased it.

So: anything that reintroduces close-confirmation, or that lets the detector fire
when price is already past the trigger, silently reverts the strategy to a version
that was measured and rejected. Hence the assertions below.
"""

import datetime as dt

import pandas as pd
import pytest
import shortcircuit.config as cfg
from shortcircuit.strategy.top_coil import TopCoilShort

BASE = 100.0  # previous close; every price below is a % of it


def _frame(closes, start="10:30"):
    """A 1-minute frame. Highs and lows equal the close, so a coil is exactly as
    tight as it looks and the fixtures stay readable."""
    h, m = (int(x) for x in start.split(":"))
    t0 = dt.datetime(2026, 9, 21, h, m)
    n = len(closes)
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime([t0 + dt.timedelta(minutes=i) for i in range(n)]),
            "open": list(closes),
            "high": list(closes),
            "low": list(closes),
            "close": list(closes),
            "volume": [10_000] * n,
        }
    )


def _run_up_then_coil(coil_px=113.0, bars_coil=20, run_bars=20):
    """Rallies to ~+13%, then goes quiet in a tight range at the high."""
    run = [100.0 + i * (coil_px - 100.0) / run_bars for i in range(run_bars)]
    coil = [coil_px + (0.05 if i % 2 else -0.05) for i in range(bars_coil)]
    return run + coil


def _gain(ltp):
    return (ltp / BASE - 1.0) * 100.0


def _evaluate(px, ltp=None, **kw):
    df = _frame(px)
    ltp = px[-1] if ltp is None else ltp
    return TopCoilShort().evaluate("NSE:T-EQ", ltp, df, _gain(ltp), **kw)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    """Config as shipped, so a test that cares about a knob sets it explicitly."""
    monkeypatch.setattr(cfg, "TOPCOIL_GAIN_MIN_PCT", 12.0, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_GAIN_MAX_PCT", 30.0, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_COIL_BARS", 15, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_NEAR_HOD_PCT", 1.5, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_MAX_RANGE_PCT", 2.0, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_BREAK_BUFFER_PCT", 0.1, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_FIRST_MIN", 585, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_LAST_MIN", 880, raising=False)


# The pattern


def test_coil_at_the_high_is_detected():
    out = _evaluate(_run_up_then_coil())
    assert out is not None
    assert out["pattern_bonus"] == "TOP_COIL_BREAKDOWN"
    assert out["exit_profile"] == "EOD_HOLD"


def test_trigger_sits_just_below_the_coil_low():
    """This level, not a confirming close, is what the engine enters on."""
    out = _evaluate(_run_up_then_coil())
    assert out is not None
    assert out["trigger_price"] == pytest.approx(out["coil_low"] * 0.999)
    assert out["signal_low_override"] == out["trigger_price"]


def test_stop_anchors_on_the_coil_high_not_the_day_high():
    """The coil high is what the measurement used. A stop at the day high is a
    wider, different trade whenever the coil forms off a lower high."""
    px = _run_up_then_coil()
    px[18] = 114.4  # an earlier high above the coil, still within 1.5%
    out = _evaluate(px)
    assert out is not None
    assert out["snapshot_high"] == out["coil_high"]
    assert out["coil_high"] < max(px)


# The gain band


def test_no_signal_below_the_gain_floor():
    """Below ~12% the same shape is a continuation pattern (up/down excursion
    ratio 1.25) and this would be shorting into the drift."""
    assert _evaluate(_run_up_then_coil(coil_px=106.0)) is None


def test_no_signal_above_the_gain_ceiling(monkeypatch):
    monkeypatch.setattr(cfg, "TOPCOIL_GAIN_MAX_PCT", 14.0, raising=False)
    assert _evaluate(_run_up_then_coil(coil_px=125.0)) is None


# The shape


def test_coil_must_sit_at_the_high():
    """A tight range 6% below the day's high is not distribution at the top."""
    px = [100.0 + i * 0.9 for i in range(20)]  # runs to ~117
    px += [110.0 + (0.05 if i % 2 else -0.05) for i in range(20)]  # coils far below
    assert _evaluate(px) is None


def test_wide_range_is_not_a_coil():
    px = [100.0 + i * 0.65 for i in range(20)]
    px += [113.0 + (1.9 if i % 2 else -1.9) for i in range(20)]  # ~3.4% wide
    assert _evaluate(px) is None


def test_short_frame_is_safe():
    assert _evaluate([100.0, 101.0, 102.0]) is None


# Causality — the failures that produced fake numbers


def test_does_not_arm_when_price_is_already_through_the_trigger():
    """Arming here would have the validation gate fire instantly, at a price the
    measurement never entered at — the same optimistic fill that turned a real
    -0.23% into a fictional +0.09%."""
    px = _run_up_then_coil()
    px += [111.5]  # already well below the coil low
    assert _evaluate(px) is None


def test_forming_bar_is_excluded_from_the_range():
    """The last row of a live frame is the bar still forming; its high and low are
    not settled. A spike on it must not widen the range and disqualify the coil."""
    px = _run_up_then_coil()
    settled = _evaluate(px)
    assert settled is not None

    spiked = _evaluate(px + [118.0])  # forming bar spikes far above
    assert spiked is not None
    assert spiked["coil_high"] == settled["coil_high"]


def test_outside_the_session_window_is_rejected(monkeypatch):
    """Before 09:45 there is no profile to coil against; after 14:40 there is no
    room for the move to pay before the 15:10 square-off."""
    px = _run_up_then_coil()
    early = _frame(px, start="09:00")
    late = _frame(px, start="14:30")
    det = TopCoilShort()
    assert det.evaluate("NSE:T-EQ", px[-1], early, _gain(px[-1])) is None
    assert det.evaluate("NSE:T-EQ", px[-1], late, _gain(px[-1])) is None


# The shared risk pre-filters still apply


@pytest.mark.parametrize(
    "kwargs",
    [
        {"is_circuit_hitter": True},
        {"upper_circuit": 113.2},
        {"spread_pct": 0.01},
    ],
)
def test_risk_prefilters_block_the_signal(kwargs):
    """Not part of the pattern — the same C0 guards the primary strategy runs. A
    second detector must not become a way around them."""
    assert _evaluate(_run_up_then_coil(), **kwargs) is None
