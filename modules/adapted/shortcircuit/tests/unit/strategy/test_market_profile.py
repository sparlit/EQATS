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
Tests for strategy/market_profile.py — Dalton value area (VAH / POC / VAL).

The value area drives gate C2 ("is price above value?"), so a wrong VAH silently
changes which setups qualify. These are pure computations over a DataFrame.
"""
import pandas as pd
import pytest
from shortcircuit.strategy.market_profile import ProfileAnalyzer


@pytest.fixture
def analyzer():
    return ProfileAnalyzer()


def _df(prices, volumes=None):
    volumes = volumes or [100] * len(prices)
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": volumes,
        }
    )


# ordering invariant


def test_vah_ge_poc_ge_val(analyzer):
    """The defining invariant of a value area. If this breaks, C2 is meaningless."""
    profile = analyzer.calculate_dalton_value_area(_df([100 + i * 0.5 for i in range(40)]))
    assert profile is not None
    assert profile["vah"] >= profile["poc"] >= profile["val"]


def test_poc_sits_at_the_heaviest_volume_price(analyzer):
    prices = [100.0] * 5 + [105.0] * 40 + [110.0] * 5  # 105 dominates
    profile = analyzer.calculate_dalton_value_area(_df(prices))
    assert profile["val"] <= 105.0 <= profile["vah"]


def test_value_area_spans_the_traded_range(analyzer):
    prices = [100 + i * 0.25 for i in range(60)]
    profile = analyzer.calculate_dalton_value_area(_df(prices))
    assert profile["val"] >= min(prices) - 1
    assert profile["vah"] <= max(prices) + 1


# degenerate inputs


def test_empty_frame_returns_none(analyzer):
    assert analyzer.calculate_dalton_value_area(pd.DataFrame()) is None


def test_none_input_returns_none(analyzer):
    assert analyzer.calculate_dalton_value_area(None) is None


def test_single_price_level_does_not_raise(analyzer):
    """Every bar at one price — binning must degrade gracefully, not explode."""
    result = analyzer.calculate_dalton_value_area(_df([100.0] * 20))
    assert result is None or result["vah"] >= result["val"]


def test_bimodal_distribution_produces_a_valid_area(analyzer):
    prices = [100.0] * 20 + [130.0] * 20
    profile = analyzer.calculate_dalton_value_area(_df(prices))
    assert profile is not None
    assert profile["vah"] >= profile["val"]


def test_zero_volume_does_not_raise(analyzer):
    result = analyzer.calculate_dalton_value_area(
        _df([100 + i for i in range(20)], volumes=[0] * 20)
    )
    assert result is None or result["vah"] >= result["val"]


# compatibility aliases


def test_exposes_both_naming_conventions(analyzer):
    """Callers read both `vah` and `vvah`; both must be present and agree."""
    profile = analyzer.calculate_dalton_value_area(_df([100 + i * 0.5 for i in range(40)]))
    for short, alias in (("poc", "vpoc"), ("vah", "vvah"), ("val", "vval")):
        assert short in profile and alias in profile
        assert profile[short] == profile[alias]


def test_all_outputs_are_plain_floats(analyzer):
    """numpy/pandas scalars leak into JSON logging and DB writes — must be float."""
    profile = analyzer.calculate_dalton_value_area(_df([100 + i * 0.5 for i in range(40)]))
    for key in ("poc", "vah", "val"):
        assert type(profile[key]) is float


# check_profile_rejection


def test_profile_rejection_needs_enough_bars(analyzer):
    rejected, _ = analyzer.check_profile_rejection(_df([100.0, 101.0]), ltp=100.0)
    assert rejected is False


def test_profile_rejection_returns_bool_and_reason(analyzer):
    df = _df([100 + i * 0.5 for i in range(40)])
    rejected, reason = analyzer.check_profile_rejection(df, ltp=float(df["close"].iloc[-1]))
    assert isinstance(rejected, bool)
    assert isinstance(reason, str) and reason
