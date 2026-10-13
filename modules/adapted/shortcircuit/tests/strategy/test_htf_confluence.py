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
Tests for G9, the higher-timeframe confluence gate.

G9 exists to stop the most expensive mistake available to this strategy: fading
a move that is still accelerating. The gate takes an injected broker client, so
a stub is all that is needed — no network, no mocking framework.

Two paths here return *allow* on unusable data rather than blocking. That is
contrary to the fail-closed policy the rest of the system follows, and it is
recorded below as `test_..._is_fail_open` so the behaviour is visible rather
than implied. Nothing in strategy/ was changed to "fix" it.
"""

import pandas as pd
import pytest
from shortcircuit import config
from shortcircuit.strategy.htf_confluence import HTFConfluence


class StubFyers:
    """Records calls and returns whatever the test queued."""

    def __init__(self, response=None, raises: bool = False):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    def history(self, data=None):
        self.calls.append(data)
        if self.raises:
            raise ConnectionError("broker unreachable")
        return self.response


def make_15m(moves_pct: list[float], *, column: str = "c", start: float = 100.0):
    """Build a 15-minute frame whose consecutive closes produce `moves_pct`."""
    closes = [start]
    for m in moves_pct:
        closes.append(closes[-1] * (1 + m / 100))
    return pd.DataFrame({column: closes})


@pytest.fixture
def gate() -> HTFConfluence:
    return HTFConfluence(StubFyers())


# alpha strike bypass


def test_extreme_stretch_bypasses_the_gate_entirely(gate):
    """Above the bypass threshold G9 passes without looking at any data."""
    allowed, msg = gate.check_trend_exhaustion(
        "NSE:TEST-EQ", vwap_sd=config.P61_G9_BYPASS_SD_THRESHOLD + 1
    )
    assert allowed is True
    assert "Alpha Strike" in msg


def test_bypass_does_not_fetch_data(gate):
    """The bypass must short-circuit before the broker call, not after it."""
    gate.check_trend_exhaustion("NSE:TEST-EQ", vwap_sd=config.P61_G9_BYPASS_SD_THRESHOLD + 1)
    assert gate.fyers.calls == [], "bypass still hit the broker"


def test_bypass_threshold_is_exclusive(gate):
    """Exactly at the threshold is not a bypass; it falls through to the physics."""
    allowed, msg = gate.check_trend_exhaustion(
        "NSE:TEST-EQ", df_15m=make_15m([0.0, 0.0]), vwap_sd=config.P61_G9_BYPASS_SD_THRESHOLD
    )
    assert "Alpha Strike" not in msg


# momentum physics


def test_accelerating_move_is_blocked(gate):
    """A still-accelerating move is the thing G9 is for."""
    accel = config.P61_G9_ACCEL_REJECT_THRESHOLD + 0.5
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=make_15m([0.1, accel]))
    assert allowed is False
    assert "Accel" in msg


def test_stalled_move_passes(gate):
    """Momentum paused at the highs is the condition reversion needs."""
    stall = config.P61_G9_STALL_PASS_THRESHOLD - 0.5
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=make_15m([1.0, stall]))
    assert allowed is True
    assert "Stall" in msg


def test_sustained_trend_between_the_thresholds_is_blocked(gate):
    """Neither accelerating nor stalled: still trending, so no entry."""
    mid = (config.P61_G9_STALL_PASS_THRESHOLD + config.P61_G9_ACCEL_REJECT_THRESHOLD) / 2
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=make_15m([0.1, mid]))
    assert allowed is False
    assert "Sustained Trend" in msg


# fail-closed on missing data


def test_missing_dataframe_blocks(gate):
    gate.fyers.response = {"s": "error"}
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ")
    assert allowed is False
    assert "Unavailable" in msg


def test_too_few_candles_blocks(gate):
    """The physics needs three closes. Two is not enough to compute acceleration."""
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=make_15m([1.0]))  # 2 rows
    assert allowed is False
    assert "Unavailable" in msg


def test_broker_exception_blocks_rather_than_propagating(gate):
    gate.fyers.raises = True
    allowed, _ = gate.check_trend_exhaustion("NSE:TEST-EQ")
    assert allowed is False


# fail-open paths, recorded deliberately


def test_unrecognised_close_column_is_fail_open(gate):
    """
    Neither 'c' nor 'close' present. The gate returns *allow*.

    This is contrary to the fail-closed policy used elsewhere: unintelligible
    data results in a trade being permitted rather than blocked. Encoded here as
    current behaviour, not endorsed. Changing it means editing strategy/.
    """
    df = pd.DataFrame({"price": [100.0, 101.0, 102.0]})
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=df)
    assert allowed is True
    assert "No close column" in msg


def test_zero_price_in_candles_is_fail_open(gate):
    """Same shape: a zero price yields allow, not block."""
    df = pd.DataFrame({"c": [100.0, 0.0, 102.0]})
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=df)
    assert allowed is True
    assert "Zero price" in msg


# column-name compatibility


@pytest.mark.parametrize("column", ["c", "close"])
def test_both_column_conventions_are_understood(gate, column):
    """
    Self-fetched HTF frames use 'c'; frames handed down from the analyzer use
    'close'. Reading the wrong one would silently disable the gate.
    """
    stall = config.P61_G9_STALL_PASS_THRESHOLD - 0.5
    allowed, _ = gate.check_trend_exhaustion(
        "NSE:TEST-EQ", df_15m=make_15m([1.0, stall], column=column)
    )
    assert allowed is True


# fetch, cache and staleness


def test_history_is_parsed_into_a_frame(gate):
    gate.fyers.response = {
        "s": "ok",
        "candles": [[1, 1, 1, 1, c, 100] for c in (100.0, 100.5, 100.6)],
    }
    df = gate._get_htf_history("NSE:TEST-EQ")
    assert df is not None and len(df) == 3


def test_second_call_within_the_ttl_is_served_from_cache(gate):
    gate.fyers.response = {
        "s": "ok",
        "candles": [[1, 1, 1, 1, c, 100] for c in (100.0, 100.5, 100.6)],
    }
    gate._get_htf_history("NSE:TEST-EQ")
    gate._get_htf_history("NSE:TEST-EQ")
    assert len(gate.fyers.calls) == 1, "cache TTL did not suppress the second fetch"


def test_malformed_response_falls_back_to_stale_cache(gate):
    """Stale data beats no data — but only because G9 blocks when it gets None."""
    gate.fyers.response = {
        "s": "ok",
        "candles": [[1, 1, 1, 1, c, 100] for c in (100.0, 100.5, 100.6)],
    }
    good = gate._get_htf_history("NSE:TEST-EQ")
    gate._htf_cache_t["NSE:TEST-EQ"] = 0  # expire it
    gate.fyers.response = {"s": "ok", "candles": [[1, 1, 1, 1, 100.0, 1]]}  # too short
    assert gate._get_htf_history("NSE:TEST-EQ") is good


def test_fetch_failure_with_no_cache_returns_none(gate):
    gate.fyers.raises = True
    assert gate._get_htf_history("NSE:UNSEEN-EQ") is None


def test_non_numeric_closes_block_rather_than_crash(gate):
    """
    Arithmetic on unusable values must not escape as an exception into the
    analyzer. The handler converts it into a block, which is the right side to
    fail on for a gate.
    """
    df = pd.DataFrame({"c": ["a", "b", "c"]})
    allowed, msg = gate.check_trend_exhaustion("NSE:TEST-EQ", df_15m=df)
    assert allowed is False
    assert "Calculation Error" in msg
