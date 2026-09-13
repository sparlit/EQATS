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


"""Smoke tests for backend/earnings.py (B3 plan item)."""
import datetime
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import earnings  # noqa: E402


class TestExtractNextEarningsDate(unittest.TestCase):
    """Regression: yfinance >= 0.2.40 returns Ticker.calendar as a *dict*,
    not a DataFrame. The original implementation called cal.empty and
    silently produced 'missing' for every symbol in production."""

    def _fake_ticker(self, calendar_payload, earnings_dates_index=None):
        class _FakeTicker:
            calendar = calendar_payload

            def get_earnings_dates(self, limit=8):
                return earnings_dates_index or []

        return _FakeTicker()

    def _run_with_stub(self, fake):
        # earnings._extract_next_earnings_date imports yfinance lazily
        # inside the function, so stubbing sys.modules is enough.
        with mock.patch.dict(sys.modules, {"yfinance": mock.MagicMock(Ticker=lambda tk: fake)}):
            return earnings._extract_next_earnings_date("X.NS")

    def test_dict_calendar_shape(self):
        """Dict-shaped calendar (modern yfinance) must parse."""
        future = datetime.date.today() + datetime.timedelta(days=30)
        result = self._run_with_stub(self._fake_ticker({"Earnings Date": [future]}))
        assert result == future.isoformat()

    def test_dict_calendar_past_only_returns_none(self):
        """Dict calendar with only past dates → None (no future date)."""
        past = datetime.date.today() - datetime.timedelta(days=10)
        result = self._run_with_stub(self._fake_ticker({"Earnings Date": [past]}, earnings_dates_index=[]))
        assert result is None

    def test_none_calendar_falls_back(self):
        """calendar=None must fall through to get_earnings_dates."""
        future = datetime.date.today() + datetime.timedelta(days=5)
        result = self._run_with_stub(self._fake_ticker(None, earnings_dates_index=[future]))
        assert result == future.isoformat()


class TestFetchEarningsUncached(unittest.TestCase):
    def test_returns_missing_when_no_dates(self):
        """No upcoming earnings date from yfinance → status='missing'."""
        with mock.patch.object(earnings, "_extract_next_earnings_date", return_value=None):
            result = earnings._fetch_earnings_uncached("RELIANCE.NS")
        assert result["status"] == "missing"
        assert result.get("data") is None
        assert result["source"] == "yfinance:earnings"

    def test_returns_ok_with_within_days(self):
        """When yfinance returns a near-future date, status='ok' + within_days
        matches the actual delta from real 'today' (no datetime mocking)."""
        with mock.patch.object(earnings, "_extract_next_earnings_date", return_value="2099-12-31"):
            result = earnings._fetch_earnings_uncached("RELIANCE.NS")
        assert result["status"] == "ok"
        assert result["data"]["earnings_date"] == "2099-12-31"
        # Far-future date → large positive within_days
        assert result["data"]["within_days"] > 1000

    def test_handles_unparseable_iso(self):
        """Bad date string from yfinance → source_failed."""
        with mock.patch.object(earnings, "_extract_next_earnings_date", return_value="not-a-date"):
            result = earnings._fetch_earnings_uncached("RELIANCE.NS")
        assert result["status"] == "source_failed"
        assert result.get("data") is None
        assert "Unparseable" in result.get("error", "")

    def test_fetch_earnings_envelope_includes_symbol(self):
        with mock.patch.object(earnings, "_extract_next_earnings_date", return_value=None):
            result = earnings.fetch_earnings("RELIANCE", "RELIANCE.NS")
        assert result["symbol"] == "RELIANCE"
        assert result["status"] == "missing"


if __name__ == "__main__":
    unittest.main()
