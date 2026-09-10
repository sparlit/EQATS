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


"""Unit tests for _nf() — NaN-safe float extractor (Issue #20).

_nf() is used across the rendering pipeline to convert yfinance values
to floats while safely handling None and NaN. Regression 1 of the v2.6.0
ETF crash (₹nan display) traced back to NaN slipping through this path.
"""

import pytest
from data_fetcher import _nf


class TestNf:
    def test_none_returns_none(self):
        assert _nf(None) is None

    def test_nan_returns_none(self):
        assert _nf(float("nan")) is None

    def test_nan_float_from_string_returns_none(self):
        assert _nf("nan") is None

    def test_positive_number_passes_through(self):
        assert _nf(100.0) == 100.0

    def test_zero_is_preserved(self):
        # 0 is falsy — callers must not use `or` on _nf output.
        assert _nf(0) == 0

    def test_negative_number_preserved(self):
        assert _nf(-12.5) == -12.5

    def test_int_coerced_to_float(self):
        result = _nf(7)
        assert isinstance(result, float)
        assert result == 7.0

    def test_numeric_string_coerced(self):
        assert _nf("42.5") == 42.5

    def test_infinity_is_not_nan_so_passthrough(self):
        # inf is a valid float, only NaN is filtered
        assert _nf(float("inf")) == float("inf")

    def test_bool_rejected_by_float_semantics(self):
        # bools are ints in Python; float(True) == 1.0. Document behavior.
        assert _nf(True) == 1.0

    @pytest.mark.parametrize("bad", ["abc", "", [], {}, object()])
    def test_unconvertible_raises_typeerror_or_valueerror(self, bad):
        with pytest.raises((TypeError, ValueError)):
            _nf(bad)

    def test_very_small_value_precision_kept(self):
        assert _nf(1e-9) == 1e-9
