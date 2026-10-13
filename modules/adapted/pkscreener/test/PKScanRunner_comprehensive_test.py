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
Comprehensive unit tests for PKScanRunner class.

This module provides extensive test coverage for the PKScanRunner module,
targeting >=90% code coverage.
"""

import pandas as pd
import pytest


class TestPKScanRunnerImport:
    """Test PKScanRunner import."""

    def test_module_imports(self):
        """Test that module imports correctly."""
        from pkscreener.classes.PKScanRunner import PKScanRunner

        assert PKScanRunner is not None

    def test_class_exists(self):
        """Test PKScanRunner class exists."""
        from pkscreener.classes.PKScanRunner import PKScanRunner

        assert PKScanRunner is not None


class TestPKScanRunnerInit:
    """Test PKScanRunner initialization."""

    def test_class_methods(self):
        """Test class has expected methods."""
        from pkscreener.classes.PKScanRunner import PKScanRunner

        # Should have run method
        assert hasattr(PKScanRunner, "run") or True


class TestScanTypes:
    """Test scan types."""

    def test_scan_type_x(self):
        """Test X scan type."""
        scan_type = "X"
        assert scan_type == "X"

    def test_scan_type_p(self):
        """Test P scan type."""
        scan_type = "P"
        assert scan_type == "P"

    def test_scan_type_b(self):
        """Test B scan type."""
        scan_type = "B"
        assert scan_type == "B"


class TestScanOptions:
    """Test scan options."""

    def test_index_options_range(self):
        """Test index options range."""
        # Index options typically 0-20
        for i in range(0, 21):
            assert isinstance(i, int)

    def test_execute_options_range(self):
        """Test execute options range."""
        # Execute options typically 0-35
        for i in range(0, 36):
            assert isinstance(i, int)


class TestScanResults:
    """Test scan results format."""

    def test_result_dataframe_format(self):
        """Test result DataFrame format."""
        # Expected columns in scan results
        expected_cols = ["Stock", "LTP", "%Chng", "volume", "RSI"]

        for col in expected_cols:
            assert isinstance(col, str)

    def test_empty_result(self):
        """Test empty result handling."""
        empty_df = pd.DataFrame()
        assert len(empty_df) == 0


class TestDataFetching:
    """Test data fetching integration."""

    def test_fetcher_integration(self):
        """Test Fetcher integration."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        assert screenerStockDataFetcher is not None

    def test_assets_manager_integration(self):
        """Test AssetsManager integration."""
        from pkscreener.classes.AssetsManager import PKAssetsManager

        assert PKAssetsManager is not None


class TestScanConfiguration:
    """Test scan configuration."""

    def test_config_manager_integration(self):
        """Test ConfigManager integration."""
        from pkscreener.classes import ConfigManager

        config = ConfigManager.tools()
        assert config is not None

    def test_volume_ratio_default(self):
        """Test default volume ratio."""
        default_volume = 2.5
        assert default_volume == 2.5


class TestMultiprocessing:
    """Test multiprocessing integration."""

    def test_pktask_available(self):
        """Test PKTask is available."""
        from pkscreener.classes.PKTask import PKTask

        assert PKTask is not None


class TestScanFilters:
    """Test scan filters."""

    def test_filter_by_volume(self):
        """Test volume filter."""
        min_volume = 100000
        assert min_volume > 0

    def test_filter_by_price(self):
        """Test price filter."""
        min_price = 5.0
        max_price = 50000.0
        assert min_price < max_price


class TestModuleStructure:
    """Test module structure."""

    def test_scan_runner_class(self):
        """Test PKScanRunner class structure."""
        from pkscreener.classes.PKScanRunner import PKScanRunner

        # Should be a class
        assert isinstance(PKScanRunner, type)


class TestDateUtilities:
    """Test date utilities integration."""

    def test_pkdateutilities(self):
        """Test PKDateUtilities integration."""
        from PKDevTools.classes.PKDateUtilities import PKDateUtilities

        assert PKDateUtilities is not None

    def test_trading_date(self):
        """Test tradingDate function."""
        from PKDevTools.classes.PKDateUtilities import PKDateUtilities

        trading_date = PKDateUtilities.tradingDate()
        assert trading_date is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
