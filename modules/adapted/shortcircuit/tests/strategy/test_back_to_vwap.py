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
Gate-by-gate tests for BackToVWAPShort — the module that decides whether real
money is committed.

The shape is a rejection table. One golden input passes all six gates; every
other case perturbs exactly one variable and asserts the evaluation returns
None. That isolates each gate: if C5 stops rejecting, only the C5 row fails, and
the row names the gate.

These tests describe what the gates *currently do*. They are a regression net,
not a correctness proof — a gate that is wrong today will have that behaviour
locked in here, deliberately, so that changing it is a visible decision rather
than an accident.

Thresholds are read from config rather than hardcoded, so retuning the strategy
does not turn this file red.
"""

import pandas as pd
import pytest
from shortcircuit import config as cfg
from shortcircuit.strategy.back_to_vwap import BackToVWAPShort

# golden input


def make_df(*, descending_highs: bool = True, fading_volume: bool = True) -> pd.DataFrame:
    """
    30 bars shaped to satisfy C4 and C5.

    Descending tail highs give `is_narrowing_highs`; a volume collapse over the
    last five bars gives a fade ratio well under the configured ceiling.
    """
    if descending_highs:
        highs = [100.0] * 24 + [104.0, 103.5, 103.0, 102.5, 102.0, 101.5]
        closes = [99.0] * 24 + [103.0, 102.5, 102.0, 101.5, 101.0, 100.5]
    else:
        # Flat tail: no narrowing highs, and no RSI divergence to fall back on.
        highs = [100.0] * 24 + [101.5] * 6
        closes = [99.0] * 24 + [100.5] * 6

    vols = [100_000] * 25 + ([5_000] * 5 if fading_volume else [100_000] * 5)

    return pd.DataFrame(
        {
            "open": [c + 0.2 for c in closes],
            "high": highs,
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": vols,
        }
    )


@pytest.fixture
def golden() -> dict:
    """Passes every gate. Each test below breaks exactly one thing."""
    return {
        "symbol": "NSE:TEST-EQ",
        "ltp": 100.5,
        "df": make_df(),
        "profile": {"vah": 101.0},
        "profile_rejection": True,
        "vwap_sd": cfg.STRATEGY_VWAP_SD_FLOOR + 1.7,
        "atr": 1.0,
        "gain_pct": cfg.SCANNER_GAIN_MIN_PCT + 2.5,
        "slope_fast": 1.0,
        "slope_slow": 10.0,
        "is_decaying": True,
    }


@pytest.fixture
def strategy() -> BackToVWAPShort:
    return BackToVWAPShort()


# the golden case


def test_all_six_gates_passing_returns_a_signal(strategy, golden):
    result = strategy.evaluate(**golden)
    assert result is not None, "golden input must pass; every rejection row depends on it"


def test_signal_carries_the_fields_the_ml_logger_records(strategy, golden):
    """
    These four were declared and passed around for months without ever being
    written (see DISCOVERIES.md). A missing key here means the ML log silently
    goes back to recording nulls.
    """
    result = strategy.evaluate(**golden)
    for key in ("confidence", "pattern_bonus", "stretch_score", "vol_fade_ratio"):
        assert key in result, f"{key} missing — ML rows would be null again"
    assert "snapshot_high" in result, "order_manager anchors the stop on snapshot_high"


def test_snapshot_high_is_the_window_high(strategy, golden):
    """The stop is placed above this value. If it under-reports, the stop is too tight."""
    result = strategy.evaluate(**golden)
    assert result["snapshot_high"] == golden["df"]["high"].max()


# rejection table: one perturbation per gate

REJECTIONS = [
    ("C0 gain below scanner floor", {"gain_pct": cfg.SCANNER_GAIN_MIN_PCT - 0.1}),
    ("C0 blacklisted circuit hitter", {"is_circuit_hitter": True}),
    ("C0 too close to upper circuit", {"upper_circuit": 101.0}),
    ("C0 too close to lower circuit", {"lower_circuit": 100.2}),
    ("C0 spread too wide", {"spread_pct": 0.01}),
    ("C1 stretch below SD floor", {"vwap_sd": cfg.STRATEGY_VWAP_SD_FLOOR - 0.1}),
    ("C2 no market profile", {"profile": None}),
    ("C2 VAH not computed", {"profile": {"vah": 0.0}}),
    ("C2 below VAH, no rejection", {"profile_rejection": False, "profile": {"vah": 200.0}}),
    ("C6 momentum not decaying", {"slope_fast": 10.0, "slope_slow": 10.0}),
]


@pytest.mark.parametrize("label,override", REJECTIONS, ids=[r[0] for r in REJECTIONS])
def test_each_gate_rejects_on_its_own(strategy, golden, label, override):
    golden.update(override)
    assert strategy.evaluate(**golden) is None, f"{label}: should have been rejected"


def test_c3_rejects_when_no_auction_failed(strategy, golden):
    """
    Price above VAH so C2 passes, but nothing probed above and closed back
    inside, and no profile rejection. C3 is the gate that must stop this.
    """
    golden["profile_rejection"] = False
    golden["profile"] = {"vah": 99.0}  # below close, so C2 is satisfied
    assert strategy.evaluate(**golden) is None


def test_c4_rejects_without_divergence(strategy, golden):
    """Flat highs: neither RSI divergence nor a price lower-high."""
    golden["df"] = make_df(descending_highs=False)
    assert strategy.evaluate(**golden) is None


def test_c5_rejects_when_volume_is_not_fading(strategy, golden):
    """Participation holding steady while price stalls is not exhaustion."""
    golden["df"] = make_df(fading_volume=False)
    assert strategy.evaluate(**golden) is None


# C6 sign-safety, the bug the branch exists to prevent


def test_c6_negative_slow_slope_does_not_invert_the_comparison(strategy, golden):
    """
    `fast < slow * 0.85` flips meaning when slow is negative: it starts
    demanding a steeper decline instead of detecting deceleration. The guarded
    branch accepts continued roll-over instead.
    """
    golden.update(slope_slow=-10.0, slope_fast=-12.0)  # still rolling over
    assert strategy.evaluate(**golden) is not None

    golden.update(slope_slow=-10.0, slope_fast=-5.0)  # decline flattening out
    assert strategy.evaluate(**golden) is None


def test_c6_requires_genuine_decay_off_a_real_up_slope(strategy, golden):
    ratio = getattr(cfg, "STRATEGY_MOMENTUM_DECAY_RATIO", 0.85)
    golden.update(slope_slow=10.0, slope_fast=10.0 * ratio - 0.01)
    assert strategy.evaluate(**golden) is not None

    golden.update(slope_fast=10.0 * ratio + 0.01)
    assert strategy.evaluate(**golden) is None


# auction failure: only two forms of evidence are accepted


def test_profile_rejection_alone_is_auction_failure():
    assert (
        BackToVWAPShort._check_auction_failure(make_df(), [], {}, vah=101.0, profile_rejection=True)
        is True
    )


def test_look_above_and_fail_is_auction_failure():
    """Probed above VAH in the last three bars, closed back inside it."""
    df = make_df()
    assert (
        BackToVWAPShort._check_auction_failure(df, [], {}, vah=101.0, profile_rejection=False)
        is True
    )


def test_narrowing_highs_alone_is_not_auction_failure():
    """
    Explicitly forbidden. Lower highs are consistent with ordinary
    consolidation and are not evidence that an auction failed.
    """
    df = make_df(descending_highs=True)
    # VAH far above the whole series: nothing can have probed above it.
    assert (
        BackToVWAPShort._check_auction_failure(df, [], {}, vah=500.0, profile_rejection=False)
        is False
    )


def test_auction_failure_is_false_without_a_vah():
    assert (
        BackToVWAPShort._check_auction_failure(make_df(), [], {}, vah=0.0, profile_rejection=False)
        is False
    )


# confidence is informational only


def test_confidence_never_changes_whether_a_signal_is_produced(strategy, golden):
    """
    The tier is recorded for later analysis and must not act as a gate. A stretch
    far below every confidence threshold still produces a signal, provided the
    six hard gates pass.
    """
    golden["vwap_sd"] = cfg.STRATEGY_VWAP_SD_FLOOR + 0.01
    result = strategy.evaluate(**golden)
    assert result is not None, "a low tier must not suppress a signal"
    assert result["confidence"] in ("MEDIUM", "HIGH", "EXTREME")


@pytest.mark.parametrize(
    "sd,confluences,expected",
    [
        (cfg.STRATEGY_VWAP_SD_EXTREME, 6, "EXTREME"),
        (cfg.STRATEGY_VWAP_SD_HIGH, 0, "HIGH"),
        (cfg.STRATEGY_VWAP_SD_FLOOR, 4, "HIGH"),
        (cfg.STRATEGY_VWAP_SD_FLOOR, 0, "MEDIUM"),
    ],
)
def test_confidence_tiers(sd, confluences, expected):
    flags = [True] * confluences + [False] * (4 - min(confluences, 4))
    assert (
        BackToVWAPShort._compute_confidence(
            vwap_sd=sd,
            vol_fade=0.1 if confluences >= 5 else 0.9,
            profile_rejection=flags[0],
            rsi_div=flags[1],
            price_lower_high=flags[2],
            auction_fail=flags[3],
        )
        == expected
    )


# no gate may be bypassed because another looks strong


@pytest.mark.parametrize(
    "gate,override",
    [
        ("C1", {"vwap_sd": cfg.STRATEGY_VWAP_SD_FLOOR - 0.1}),
        ("C5", {"df": make_df(fading_volume=False)}),
        ("C6", {"slope_fast": 10.0, "slope_slow": 10.0}),
    ],
)
def test_an_extreme_setup_still_cannot_skip_a_failing_gate(strategy, golden, gate, override):
    """
    An earlier revision let a volume climax override the volume-fade gate. Every
    other signal here is maximally strong; the one broken gate must still reject.
    """
    golden.update(vwap_sd=cfg.STRATEGY_VWAP_SD_EXTREME + 5, gain_pct=17.0)
    golden.update(override)
    assert strategy.evaluate(**golden) is None, f"{gate} was bypassed"
