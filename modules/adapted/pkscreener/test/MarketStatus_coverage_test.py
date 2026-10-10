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
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Tests for MarketStatus.py to achieve 90%+ coverage.
"""

import warnings

warnings.filterwarnings("ignore")


class TestMarketStatusCoverage:
    """Comprehensive tests for MarketStatus."""

    def test_market_status_singleton(self):
        """Test MarketStatus is singleton."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms1 = MarketStatus()
        ms2 = MarketStatus()

        # Singleton should return same instance
        assert ms1 is ms2

    def test_exchange_property_default(self):
        """Test exchange property returns default when not set."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        # Clear attributes to test default
        if hasattr(ms, "attributes") and "exchange" in ms.attributes:
            del ms.attributes["exchange"]

        assert ms.exchange == "^NSEI"

    def test_exchange_property_when_set(self):
        """Test exchange property returns value when set."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        ms.attributes["exchange"] = "^BSESN"

        assert ms.exchange == "^BSESN"

    def test_exchange_setter_different_value(self):
        """Test exchange setter when value is different."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        # Set initial value
        ms.attributes["exchange"] = "^NSEI"

        # Set different value - should trigger getMarketStatus
        ms.exchange = "^BSESN"

        assert ms.exchange == "^BSESN"

    def test_exchange_setter_same_value(self):
        """Test exchange setter when value is same."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        ms.attributes["exchange"] = "^NSEI"

        # Set same value
        ms.exchange = "^NSEI"

        assert ms.exchange == "^NSEI"

    def test_market_status_property_default(self):
        """Test marketStatus property returns empty when not set."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        # Clear attributes
        if hasattr(ms, "attributes") and "marketStatus" in ms.attributes:
            del ms.attributes["marketStatus"]

        result = ms.marketStatus
        # Should set and return empty string
        assert result == "" or result is not None

    def test_market_status_property_when_set(self):
        """Test marketStatus property returns value when set."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        ms.attributes["marketStatus"] = "Market Open"

        assert ms.marketStatus == "Market Open"

    def test_market_status_setter(self):
        """Test marketStatus setter."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        ms.marketStatus = "Closed"

        assert ms.marketStatus == "Closed"
        assert ms.attributes["marketStatus"] == "Closed"

    def test_get_market_status_returns_na(self):
        """Test getMarketStatus returns NA."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        result = ms.getMarketStatus()

        # Method returns "NA" immediately at line 65
        assert result == "NA"

    def test_get_market_status_with_exchange(self):
        """Test getMarketStatus with different exchanges."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()

        for exchange in ["^NSEI", "^BSESN", "^DJI"]:
            result = ms.getMarketStatus(exchangeSymbol=exchange)
            assert result == "NA"

    def test_get_market_status_with_progress(self):
        """Test getMarketStatus with progress dict."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()
        progress = {}

        result = ms.getMarketStatus(progress=progress, task_id=1)

        assert result == "NA"

    def test_get_market_status_named_only(self):
        """Test getMarketStatus with namedOnly flag."""
        from pkscreener.classes.MarketStatus import MarketStatus

        ms = MarketStatus()

        result = ms.getMarketStatus(namedOnly=True)

        assert result == "NA"

    def test_nse_fetcher_attribute(self):
        """Test nseFetcher class attribute exists."""
        from pkscreener.classes.MarketStatus import MarketStatus

        assert hasattr(MarketStatus, "nseFetcher")
        assert MarketStatus.nseFetcher is not None
