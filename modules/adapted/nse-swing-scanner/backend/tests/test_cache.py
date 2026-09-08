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


"""Tests for the on-disk cache."""
import json
import os
import tempfile
import time
from unittest.mock import patch

import fscore
import numpy as np
import pandas as pd
import pytest
import technicals
from cache import clear_cache, read_cache, write_cache


def test_write_read_roundtrip(tmp_path):
    write_cache("foo:bar", {"hello": "world"}, cache_dir=str(tmp_path))
    got = read_cache("foo:bar", cache_dir=str(tmp_path))
    assert got == {"hello": "world"}


def test_missing_returns_none(tmp_path):
    assert read_cache("never:written", cache_dir=str(tmp_path)) is None


def test_max_age_expired(tmp_path):
    write_cache("foo:expired", {"v": 1}, cache_dir=str(tmp_path))
    # Manually backdate the mtime
    p = os.path.join(str(tmp_path), "foo_expired.json")
    old = time.time() - 999
    os.utime(p, (old, old))
    assert read_cache("foo:expired", cache_dir=str(tmp_path), max_age_seconds=10) is None
    # No max age returns it
    assert read_cache("foo:expired", cache_dir=str(tmp_path)) == {"v": 1}


def test_unsafe_key_is_sanitized(tmp_path):
    write_cache("weird/key with spaces!", {"x": 1}, cache_dir=str(tmp_path))
    got = read_cache("weird/key with spaces!", cache_dir=str(tmp_path))
    assert got == {"x": 1}
    # And the file exists with a sanitized name
    files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".json")]
    assert any("weird_key_with_spaces" in f for f in files)


def test_clear_cache(tmp_path):
    write_cache("a:1", {"v": 1}, cache_dir=str(tmp_path))
    write_cache("a:2", {"v": 2}, cache_dir=str(tmp_path))
    n = clear_cache(cache_dir=str(tmp_path))
    assert n == 2
    assert read_cache("a:1", cache_dir=str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Regression: yfinance cache wrappers must import all referenced TTL constants.
#
# Background: a 1.1.3 change added on-disk caching to compute_fscore and
# approx_5y_avg_pe in backend/fscore.py. The wrapper in approx_5y_avg_pe
# referenced YF_CACHE_TTL_SECONDS but only YF_FUNDAMENTAL_CACHE_TTL_SECONDS
# was imported, raising NameError at runtime in production. conftest.py sets
# NSE_SWING_NO_CACHE=1 to bypass the cache branch in tests, so this was
# uncaught by the existing 76-test suite.
#
# These tests exercise the cache wrapper paths directly (NSE_SWING_NO_CACHE
# unset) and assert no NameError on import / symbol resolution. They also
# write a fixture to the on-disk cache so we can assert cache reads work.
# ---------------------------------------------------------------------------


@pytest.fixture
def _cache_enabled(monkeypatch):
    """Enable the on-disk cache for the wrapped compute_* functions."""
    monkeypatch.delenv("NSE_SWING_NO_CACHE", raising=False)
    # Note: we deliberately write to the real backend/cache/ directory
    # because the wrappers call read_cache/write_cache with their default
    # cache_dir (a module-level constant that's bound at function-definition
    # time, so we can't redirect it here without invasive patching). The
    # fixture data is overwritten on the next real run.
    yield
    # Best-effort cleanup of the entries this fixture wrote.
    from cache import DEFAULT_CACHE_DIR, cache_path

    for key in (
        "tech:RELIANCE.NS:1y",
        "tech:^NSEI:1y",
        "fscore:RELIANCE.NS",
        "pe5y:RELIANCE.NS",
        "tech:TCS.NS:1y",
    ):
        try:
            p = cache_path(DEFAULT_CACHE_DIR, key)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _fake_history(n=260, trailing_nan=0):
    """Synthetic yfinance .history() output with optional trailing NaN bars."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    np.random.seed(7)
    prices = 100 + np.cumsum(np.random.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "Open": prices + np.random.normal(0, 0.5, n),
            "High": prices + np.abs(np.random.normal(0, 1, n)),
            "Low": prices - np.abs(np.random.normal(0, 1, n)),
            "Close": prices,
            "Volume": np.random.randint(1_000_000, 5_000_000, n).astype(float),
        },
        index=dates,
    )
    if trailing_nan:
        df.iloc[-trailing_nan:, 0:5] = np.nan
    return df


def test_compute_technicals_cache_wrapper_resolves_all_constants(_cache_enabled):
    """compute_technicals must not raise NameError when cache is enabled."""
    hist = _fake_history()
    with patch.object(technicals.yf, "Ticker") as fake_ticker:
        fake_ticker.return_value.history.return_value = hist
        result = technicals.compute_technicals("RELIANCE.NS")
    assert result["error"] is None
    assert "current_price" in result


def test_compute_nifty50_context_cache_wrapper_resolves_all_constants(_cache_enabled):
    """compute_nifty50_context must not raise NameError when cache is enabled."""
    hist = _fake_history()
    with patch.object(technicals.yf, "Ticker") as fake_ticker:
        fake_ticker.return_value.history.return_value = hist
        result = technicals.compute_nifty50_context()
    assert result["error"] is None


def test_compute_fscore_cache_wrapper_resolves_all_constants(_cache_enabled):
    """compute_fscore must not raise NameError when cache is enabled."""
    fake_df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    with patch.object(fscore.yf, "Ticker") as fake_ticker:
        t = fake_ticker.return_value
        t.financials = fake_df
        t.balance_sheet = fake_df
        t.cashflow = fake_df
        result = fscore.compute_fscore("RELIANCE.NS")
    # Two-column frame isn't enough for fscore (needs >=2 fiscal years), but
    # the wrapper must not NameError before that check.
    assert "error" in result


def test_approx_5y_avg_pe_cache_wrapper_resolves_all_constants(_cache_enabled):
    """approx_5y_avg_pe must not raise NameError when cache is enabled.

    This is the regression case from the 1.1.3 review: fscore.py referenced
    YF_CACHE_TTL_SECONDS without importing it, causing NameError at runtime.
    """
    hist = _fake_history(n=260 * 6)
    fy_dates = pd.to_datetime(["2023-03-31", "2024-03-31", "2025-03-31"])
    fake_fin = pd.DataFrame(
        [[10.0, 12.0, 14.0]],
        index=["Diluted EPS"],
        columns=fy_dates,
    )
    with patch.object(fscore.yf, "Ticker") as fake_ticker:
        t = fake_ticker.return_value
        t.financials = fake_fin
        t.history.return_value = hist
        t.info.get.return_value = 25.0  # trailingPE
        result = fscore.approx_5y_avg_pe("RELIANCE.NS")
    # Whatever the value, the function must have run without NameError.
    assert "avg_pe_5y" in result or result.get("error") not in (None, "")


def test_cache_wrapper_writes_and_replays(_cache_enabled):
    """A successful compute_technicals call must populate the cache so the
    next call returns without invoking yfinance."""
    hist = _fake_history()
    with patch.object(technicals.yf, "Ticker") as fake_ticker:
        fake_ticker.return_value.history.return_value = hist
        first = technicals.compute_technicals("TCS.NS")

    # Second call: yf.Ticker should NOT be invoked if the cache hit short-
    # circuits before the yfinance call.
    with patch.object(technicals.yf, "Ticker") as fake_ticker:
        fake_ticker.return_value.history.side_effect = AssertionError("yfinance should not be called on cache hit")
        second = technicals.compute_technicals("TCS.NS")

    assert first == second
