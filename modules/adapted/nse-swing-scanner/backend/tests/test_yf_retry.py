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


"""Tests for backend/yf_retry.py."""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest
import yf_retry  # noqa: E402
from cache import cached_call, read_cache  # noqa: E402


class TestRateLimitDetection(unittest.TestCase):
    def test_markers(self):
        assert yf_retry.is_rate_limit_error("Too Many Requests. Rate limited.")
        assert yf_retry.is_rate_limit_error(Exception("HTTP 429"))
        assert not yf_retry.is_rate_limit_error("insufficient_history")
        assert yf_retry.is_rate_limit_payload(
            {"error": "fetch_failed: Too Many Requests. Rate limited.", "f_score": None}
        )
        assert not yf_retry.is_rate_limit_payload({"error": None})
        assert not yf_retry.should_cache_yf_payload({"error": "fetch_failed: rate limited"})
        assert yf_retry.should_cache_yf_payload({"error": None, "rsi14": 30})


class TestCallWithRetry(unittest.TestCase):
    def test_succeeds_first_try(self):
        assert yf_retry.call_with_retry(lambda: 42, max_attempts=3) == 42

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                msg = "Too Many Requests. Rate limited."
                raise RuntimeError(msg)
            return "ok"

        with patch("yf_retry.time.sleep"):
            assert yf_retry.call_with_retry(flaky, max_attempts=3, base_delay_s=0.01) == "ok"
        assert calls["n"] == 3

    def test_retries_on_retryable_result(self):
        calls = {"n": 0}

        def empty_then_data():
            calls["n"] += 1
            if calls["n"] < 2:
                return {}
            return {"Close": 1}

        with patch("yf_retry.time.sleep"):
            got = yf_retry.call_with_retry(
                empty_then_data,
                max_attempts=3,
                base_delay_s=0.01,
                retryable_result=lambda d: not d,
            )
        assert got == {"Close": 1}

    def test_non_retryable_raises_immediately(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            msg = "hard fail"
            raise ValueError(msg)

        with pytest.raises(ValueError):
            yf_retry.call_with_retry(boom, max_attempts=3)
        assert calls["n"] == 1


class TestCachedCallShouldCache(unittest.TestCase):
    def test_rate_limit_not_written(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            # Ensure cache is enabled
            old = os.environ.pop("NSE_SWING_NO_CACHE", None)
            try:
                result = cached_call(
                    "rl:test",
                    3600,
                    lambda: {"error": "fetch_failed: Too Many Requests. Rate limited."},
                    cache_dir=tmp,
                    should_cache=yf_retry.should_cache_yf_payload,
                )
                assert "Too Many" in result["error"]
                assert read_cache("rl:test", cache_dir=tmp) is None

                ok = cached_call(
                    "ok:test",
                    3600,
                    lambda: {"error": None, "v": 1},
                    cache_dir=tmp,
                    should_cache=yf_retry.should_cache_yf_payload,
                )
                assert ok["v"] == 1
                assert read_cache("ok:test", cache_dir=tmp)["v"] == 1
            finally:
                if old is not None:
                    os.environ["NSE_SWING_NO_CACHE"] = old
                else:
                    os.environ["NSE_SWING_NO_CACHE"] = "1"

    def test_poisoned_rate_limit_cache_is_ignored_on_read(self):
        """Pre-1.3.1 entries that cached 429 payloads must not short-circuit."""
        import tempfile

        from cache import write_cache

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.pop("NSE_SWING_NO_CACHE", None)
            try:
                write_cache(
                    "tech:poison",
                    {"error": "fetch_failed: Too Many Requests. Rate limited.", "yf_ticker": "X.NS"},
                    cache_dir=tmp,
                )
                calls = {"n": 0}

                def live():
                    calls["n"] += 1
                    return {"error": None, "current_price": 100.0}

                got = cached_call(
                    "tech:poison",
                    3600,
                    live,
                    cache_dir=tmp,
                    should_cache=yf_retry.should_cache_yf_payload,
                )
                assert got["current_price"] == 100.0
                assert calls["n"] == 1
                # Poison file deleted; good result written
                assert read_cache("tech:poison", cache_dir=tmp)["current_price"] == 100.0
            finally:
                if old is not None:
                    os.environ["NSE_SWING_NO_CACHE"] = old
                else:
                    os.environ["NSE_SWING_NO_CACHE"] = "1"


if __name__ == "__main__":
    unittest.main()
