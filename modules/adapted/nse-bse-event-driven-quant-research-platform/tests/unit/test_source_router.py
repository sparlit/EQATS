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


"""Fault-injection tests for SourceRouter circuit breaker and fallback cascade."""


import time
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
from indian_quant.ingestion.router import CircuitBreaker, SourceRouter


class TestCircuitBreaker:
    def test_opens_after_three_failures(self):
        cb = CircuitBreaker(fail_fast=3)
        cb.record_failure("src")
        cb.record_failure("src")
        assert not cb.is_open("src")
        cb.record_failure("src")
        assert cb.is_open("src")

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(fail_fast=3)
        cb.record_failure("src")
        cb.record_failure("src")
        cb.record_success("src")
        assert not cb.is_open("src")

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(fail_fast=2, half_open_after_ms=100)
        cb.record_failure("src")
        cb.record_failure("src")
        assert cb.is_open("src")
        time.sleep(0.15)
        assert not cb.is_open("src")

    def test_different_sources_independent(self):
        cb = CircuitBreaker(fail_fast=2)
        cb.record_failure("a")
        cb.record_failure("a")
        assert cb.is_open("a")
        assert not cb.is_open("b")


class TestSourceRouterFaultInjection:
    def test_bse_cascades_to_yfinance_on_upstox_failure(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_bseindia_bars", return_value=None),
            patch.object(
                router,
                "_yfinance_bars",
                return_value=pd.DataFrame({"close": [100]}),
            ) as mock_yf,
        ):
            result = router.get_bars_bse("TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2))
            assert result is not None
            mock_yf.assert_called_once()

    def test_nse_cascades_to_yfinance_on_all_failures(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_nse_bhavcopy", return_value=None),
            patch.object(
                router,
                "_yfinance_bars",
                return_value=pd.DataFrame({"close": [100]}),
            ) as mock_yf,
        ):
            result = router.get_bars_nse("TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2))
            assert result is not None
            mock_yf.assert_called_once_with("TEST", date(2025, 1, 1), date(2025, 1, 2), suffix=".NS")

    def test_returns_none_when_all_sources_exhausted(self):
        router = SourceRouter()
        with (
            patch.object(router, "_upstox_bars", return_value=None),
            patch.object(router, "_bseindia_bars", return_value=None),
            patch.object(router, "_yfinance_bars", return_value=None),
        ):
            result = router.get_bars_bse("TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2))
            assert result is None

    def test_circuit_breaker_skips_source_when_open(self):
        router = SourceRouter()
        router.cb.record_failure("upstox")
        router.cb.record_failure("upstox")
        router.cb.record_failure("upstox")
        # With CB open, _upstox_bars returns None before importing the client.
        # get_bars_nse should cascade past Upstox to bhavcopy and yfinance.
        with (
            patch.object(router, "_nse_bhavcopy", return_value=None),
            patch.object(router, "_yfinance_bars", return_value=pd.DataFrame({"c": [1]})) as mock_yf,
        ):
            result = router.get_bars_nse("TEST", from_date=date(2025, 1, 1), to_date=date(2025, 1, 2))
            assert result is not None
            mock_yf.assert_called_once()

    def test_fundamentals_cascade(self):
        router = SourceRouter()
        with (
            patch.object(router, "_finstack_key_ratios", return_value=None),
            patch.object(router, "_indian_market_market_cap", return_value=None),
            patch.object(
                router,
                "_get_free_mcp",
            ) as mock_free_mcp,
        ):
            mock_client = MagicMock()
            mock_client.call_tool.return_value = {"pe": 25.0}
            mock_free_mcp.return_value = mock_client
            result = router.get_fundamentals("TEST")
            assert result == {"pe": 25.0}
            mock_client.call_tool.assert_called_once()

    def test_market_cap_cascade(self):
        router = SourceRouter()
        with (
            patch.object(router, "_finstack_market_cap", return_value=None),
            patch.object(router, "_indian_market_market_cap", return_value=None),
            patch("yfinance.Ticker") as mock_ticker_cls,
        ):
            mock_ticker = MagicMock()
            mock_ticker.info = {"marketCap": 1_000_000_000}
            mock_ticker_cls.return_value = mock_ticker
            result = router.get_market_cap("TEST")
            assert result == 1_000_000_000
