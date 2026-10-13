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
The VWAP anchor invariant.

`features.enrich_dataframe` computes a *cumulative* VWAP:

    df['vwap'] = (tp * v).cumsum() / v.cumsum()

which is the session VWAP only if the frame it receives begins at the session
open. Hand it a truncated frame and it silently returns a rolling-window VWAP
anchored to wherever that frame starts — no error, no warning, just a different
indicator wearing the same name.

BUG-2026-08-12: `analyzer.get_history` requested 100 bars from the local
aggregator, so C1 measured stretch against a ~100-minute sliding anchor. On
NSE:ORISSAMINE-EQ the anchor sat on the day's peak and the stock read as 1.52 SD
*below* VWAP while a session-anchored VWAP had it above. 295 of that session's
340 scans used that path.

These tests pin the invariant rather than the fix, so a future change to how
history is fetched cannot quietly reintroduce a sliding anchor.
"""

import numpy as np
import pandas as pd
import pytest
from shortcircuit.execution.analyzer import (
    SESSION_BARS_1M,
    frame_reaches_session_open,
)
from shortcircuit.strategy.features import compute_vwap_sd, enrich_dataframe


def orissamine_shaped(n_bars: int = 161, peak_at: int = 75):
    """
    A morning ramp into a peak, then a fade — the shape that exposes the bug.
    Open 100 → peak 130 around bar 75 → 121 by the end.
    """
    closes = np.concatenate(
        [
            np.linspace(100, 130, peak_at),
            np.linspace(130, 121, n_bars - peak_at),
        ]
    )
    return pd.DataFrame(
        {
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": np.full(n_bars, 2000.0),
        }
    )


def sd_of(df: pd.DataFrame) -> float:
    d = df.copy()
    enrich_dataframe(d)
    return compute_vwap_sd(d)


# the regression


def test_truncating_the_frame_changes_the_sign_of_the_stretch():
    """
    The whole bug in one assertion: identical price data, two frame lengths,
    opposite conclusions about which side of VWAP price is on.
    """
    full = orissamine_shaped()
    truncated = full.iloc[-100:].reset_index(drop=True)

    assert sd_of(full) > 0, "session-anchored VWAP puts price above VWAP"
    assert sd_of(truncated) < 0, "100-bar anchor puts price below VWAP"


def test_a_truncated_frame_anchors_vwap_higher():
    """
    Cutting off the cheap early-session bars raises the anchor, which is exactly
    why the stretch flipped negative.
    """
    full = orissamine_shaped().copy()
    truncated = full.iloc[-100:].reset_index(drop=True).copy()
    enrich_dataframe(full)
    enrich_dataframe(truncated)

    assert truncated["vwap"].iloc[-1] > full["vwap"].iloc[-1]


def test_the_session_request_covers_a_full_trading_day():
    """09:15–15:30 IST is 375 one-minute bars; the request must exceed that."""
    assert SESSION_BARS_1M >= 375


# the guard that catches a mid-session restart


def frame_starting_at(hhmm: str, n: int = 30) -> pd.DataFrame:
    idx = pd.date_range(f"2026-08-12 {hhmm}", periods=n, freq="1min", tz="Asia/Kolkata")
    return pd.DataFrame({"datetime": idx, "close": np.linspace(100, 110, n)})


@pytest.mark.parametrize(
    "start,expected",
    [
        ("09:15", True),  # the open itself
        ("09:16", True),  # one minute of slack for a late first tick
        ("09:20", False),  # already past the open
        ("10:16", False),  # the ORISSAMINE anchor
        ("13:00", False),  # afternoon restart
    ],
)
def test_only_a_frame_starting_at_the_open_is_session_anchored(start, expected):
    assert frame_reaches_session_open(frame_starting_at(start)) is expected


@pytest.mark.parametrize("df", [None, pd.DataFrame(), pd.DataFrame({"close": [1, 2]})])
def test_unusable_frames_are_not_treated_as_session_anchored(df):
    """
    Fail closed. Claiming a frame is session-anchored when it cannot be verified
    would reintroduce the bug silently, which is how it survived this long.
    """
    assert frame_reaches_session_open(df) is False


# the property the gate actually depends on


def test_stretch_is_positive_when_price_is_above_the_session_vwap():
    """
    C1 shorts overextension ABOVE VWAP. If a stock that spent the session
    climbing does not report a positive stretch, the gate is measuring something
    other than what it claims to.
    """
    rising = pd.DataFrame(
        {
            "high": np.linspace(100, 140, 200) * 1.002,
            "low": np.linspace(100, 140, 200) * 0.998,
            "close": np.linspace(100, 140, 200),
            "volume": np.full(200, 1000.0),
        }
    )
    assert sd_of(rising) > 0


def test_stretch_is_negative_when_price_is_below_the_session_vwap():
    falling = pd.DataFrame(
        {
            "high": np.linspace(140, 100, 200) * 1.002,
            "low": np.linspace(140, 100, 200) * 0.998,
            "close": np.linspace(140, 100, 200),
            "volume": np.full(200, 1000.0),
        }
    )
    assert sd_of(falling) < 0


# the broker returning more than it was asked for


def two_session_frame() -> pd.DataFrame:
    """
    What a range_from == range_to == today request actually came back with on
    2026-08-12: 750 bars covering two full sessions.
    """
    idx = pd.to_datetime(
        [f"2026-08-11 {9 + i // 60:02d}:{i % 60:02d}" for i in range(15, 30)]
        + [f"2026-08-12 {9 + i // 60:02d}:{i % 60:02d}" for i in range(15, 30)]
    ).tz_localize("Asia/Kolkata")
    return pd.DataFrame(
        {
            "datetime": idx,
            "high": np.linspace(100, 140, len(idx)) * 1.002,
            "low": np.linspace(100, 140, len(idx)) * 0.998,
            "close": np.linspace(100, 140, len(idx)),
            "volume": np.full(len(idx), 1000.0),
        }
    )


def test_extra_sessions_are_dropped():
    import datetime as _dt

    from shortcircuit.execution.analyzer import keep_session_only

    kept = keep_session_only(two_session_frame(), _dt.date(2026, 8, 12))
    assert len(kept) == 15
    assert set(kept["datetime"].dt.date) == {_dt.date(2026, 8, 12)}


def test_a_two_session_frame_anchors_vwap_to_the_wrong_day():
    """
    Why the filter exists. Leaving yesterday's bars in moves the anchor further
    than the 100-bar window ever did, so an unfiltered response is a worse bug
    than the one it replaced.
    """
    import datetime as _dt

    from shortcircuit.execution.analyzer import keep_session_only

    both = two_session_frame().copy()
    today_only = keep_session_only(two_session_frame(), _dt.date(2026, 8, 12)).copy()
    enrich_dataframe(both)
    enrich_dataframe(today_only)

    assert both["vwap"].iloc[-1] < today_only["vwap"].iloc[-1], (
        "yesterday's cheaper bars drag the anchor down and inflate the stretch"
    )


def test_filtering_a_single_session_frame_changes_nothing():
    import datetime as _dt

    from shortcircuit.execution.analyzer import keep_session_only

    one = two_session_frame()
    one = one[one["datetime"].dt.date == _dt.date(2026, 8, 12)].reset_index(drop=True)
    assert len(keep_session_only(one, _dt.date(2026, 8, 12))) == len(one)


def test_duplicate_and_unordered_bars_are_repaired():
    """
    A single-session request returned 750 rows for 375 unique epochs, out of
    order. Volume double-counts and df.iloc[-1] stops being the latest bar.
    """
    import datetime as _dt

    from shortcircuit.execution.analyzer import keep_session_only

    idx = pd.date_range("2026-08-12 09:15", periods=5, freq="1min", tz="Asia/Kolkata")
    base = pd.DataFrame(
        {
            "epoch": [int(t.timestamp()) for t in idx],
            "datetime": idx,
            "volume": [100.0] * 5,
            "close": [10.0, 11, 12, 13, 14],
        }
    )
    scrambled = pd.concat([base.iloc[[3, 1]], base, base.iloc[[0, 4]]], ignore_index=True)

    out = keep_session_only(scrambled, _dt.date(2026, 8, 12))
    assert len(out) == 5, "duplicates survived"
    assert out["epoch"].is_monotonic_increasing, "bars not sorted"
    assert out["volume"].sum() == 500.0, "volume was double-counted"
    assert out["close"].iloc[-1] == 14.0, "iloc[-1] must be the latest bar"
