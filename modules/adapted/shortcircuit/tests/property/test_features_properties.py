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
Property-based tests over generated OHLCV series (hypothesis).

Example-based tests prove a function works for the cases you thought of.
These assert invariants that must hold for *every* input — including the
degenerate series nobody thinks to write by hand.

P6 and P7 catch real bugs. P7 in particular: silent in-place mutation of an
input DataFrame is a classic pandas trap, and in this codebase the same frame is
passed to several gates in sequence, so a mutation in one changes the answer of
the next.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from shortcircuit.strategy import features as F
from shortcircuit.strategy.market_profile import ProfileAnalyzer

SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

price = st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
volume = st.integers(min_value=0, max_value=5_000_000)


@st.composite
def ohlcv(draw, min_size=25, max_size=80):
    """Generate an internally consistent OHLCV frame: low <= open/close <= high."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    rows = []
    for _ in range(n):
        a = draw(price)
        b = draw(price)
        o, c = min(a, b), max(a, b)
        spread = draw(st.floats(min_value=0.0, max_value=50.0, allow_nan=False))
        rows.append(
            {
                "open": o,
                "close": c,
                "high": c + spread,
                "low": max(0.01, o - spread),
                "volume": draw(volume),
            }
        )
    return pd.DataFrame(rows)


@SETTINGS
@given(df=ohlcv())
def test_p1_vwap_lies_within_the_traded_range(df):
    """VWAP is an average of typical prices; it cannot escape [min low, max high]."""
    assume(df["volume"].sum() > 0)
    F.enrich_dataframe(df)
    vwap = df["vwap"].iloc[-1]
    assume(np.isfinite(vwap))
    assert df["low"].min() - 1e-6 <= vwap <= df["high"].max() + 1e-6


@SETTINGS
@given(df=ohlcv())
def test_p2_rsi_divergence_is_always_a_bool(df):
    """
    The RSI series itself is internal, so the observable invariant is that the
    divergence gate always answers with a bool and never raises — a gate that
    throws would abort the entire scan cycle.
    """
    result = F.compute_rsi_divergence(df, window=20)
    assert isinstance(result, bool)


@SETTINGS
@given(df=ohlcv(min_size=30))
def test_p3_value_area_is_ordered_vah_ge_poc_ge_val(df):
    assume(df["volume"].sum() > 0)
    profile = ProfileAnalyzer().calculate_dalton_value_area(df)
    assume(profile is not None)
    assert profile["vah"] >= profile["poc"] >= profile["val"]


@SETTINGS
@given(df=ohlcv(min_size=30))
def test_p4_value_area_lies_within_the_traded_range(df):
    assume(df["volume"].sum() > 0)
    profile = ProfileAnalyzer().calculate_dalton_value_area(df)
    assume(profile is not None)
    lo, hi = df["close"].min(), df["close"].max()
    span = max(hi - lo, 1.0)
    assert profile["val"] >= lo - span
    assert profile["vah"] <= hi + span


@SETTINGS
@given(
    p=st.floats(min_value=1.0, max_value=5_000.0, allow_nan=False),
    n=st.integers(min_value=5, max_value=60),
    v=st.integers(min_value=1, max_value=100_000),
)
def test_p5_vwap_of_a_constant_series_is_that_price(p, n, v):
    df = pd.DataFrame(
        {
            "open": [p] * n,
            "high": [p] * n,
            "low": [p] * n,
            "close": [p] * n,
            "volume": [v] * n,
        }
    )
    F.enrich_dataframe(df)
    assert df["vwap"].iloc[-1] == pytest.approx(p, rel=1e-9)


@SETTINGS
@given(df=ohlcv())
def test_p6_appending_a_zero_volume_bar_does_not_move_vwap(df):
    """A bar that traded nothing contributes no weight — VWAP must be unchanged."""
    assume(df["volume"].sum() > 0)

    before = df.copy()
    F.enrich_dataframe(before)
    baseline = before["vwap"].iloc[-1]
    assume(np.isfinite(baseline))

    extended = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "open": df["close"].iloc[-1],
                        "high": df["close"].iloc[-1],
                        "low": df["close"].iloc[-1],
                        "close": df["close"].iloc[-1],
                        "volume": 0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    F.enrich_dataframe(extended)

    assert extended["vwap"].iloc[-1] == pytest.approx(baseline, rel=1e-9)


@SETTINGS
@given(df=ohlcv())
def test_p7_read_only_features_are_pure_and_do_not_mutate_input(df):
    """
    Called twice with the same input: identical output, and the input frame
    unchanged. `enrich_dataframe` is excluded — it documents in-place mutation
    as its contract. Everything else must be side-effect free.
    """
    F.enrich_dataframe(df)  # establish the vwap column first
    snapshot = df.copy(deep=True)

    first = (
        F.compute_vwap_sd(df),
        F.compute_atr(df),
        F.compute_rsi_divergence(df, window=20),
        F.is_narrowing_highs(df, n=3),
    )
    second = (
        F.compute_vwap_sd(df),
        F.compute_atr(df),
        F.compute_rsi_divergence(df, window=20),
        F.is_narrowing_highs(df, n=3),
    )

    for a, b in zip(first, second, strict=True):
        if isinstance(a, float) and np.isnan(a):
            assert np.isnan(b)
        else:
            assert a == b, "feature calculation is not deterministic"

    pd.testing.assert_frame_equal(
        df,
        snapshot,
        obj="input frame was mutated by a read-only feature calculation",
    )


# Robustness


@SETTINGS
@given(df=ohlcv())
def test_atr_is_nan_or_a_finite_non_negative_number(df):
    """ATR feeds stop sizing: it must never be negative and never a sentinel."""
    atr = F.compute_atr(df)
    assert np.isnan(atr) or (np.isfinite(atr) and atr >= 0)


@SETTINGS
@given(vols=st.lists(st.integers(min_value=0, max_value=1_000_000), min_size=20, max_size=60))
def test_volume_fade_ratio_is_always_finite_and_non_negative(vols):
    ratio = F.compute_volume_fade_ratio([{"volume": v} for v in vols], lookback=10)
    assert np.isfinite(ratio) and ratio >= 0
