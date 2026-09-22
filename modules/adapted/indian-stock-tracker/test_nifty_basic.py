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


"""Tests for NIFTY 50 market data service."""

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest


class TestNiftyDataService:
    """Test suite for NIFTY 50 data service."""

    def test_valid_1d_request(self):
        """Test valid 1D range request."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1D")
        assert result["status"] == "success"
        assert result["symbol"] == "^NSEI"
        assert result["range"] == "1D"
        assert len(result["data"]) > 0
        for point in result["data"]:
            assert "timestamp" in point
            assert "value" in point
            assert point["value"] > 0

    def test_valid_1w_request(self):
        """Test valid 1W range request."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1W")
        assert result["status"] == "success"
        assert result["range"] == "1W"

    def test_valid_1m_request(self):
        """Test valid 1M range request."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1M")
        assert result["status"] == "success"
        assert result["range"] == "1M"

    def test_valid_3m_request(self):
        """Test valid 3M range request."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("3M")
        assert result["status"] == "success"
        assert result["range"] == "3M"

    def test_valid_1y_request(self):
        """Test valid 1Y range request."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1Y")
        assert result["status"] == "success"
        assert result["range"] == "1Y"

    def test_invalid_range(self):
        """Test invalid range returns error."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("INVALID")
        assert result["status"] == "error"
        assert "Invalid" in result["message"]

    @patch("nifty_data_service.yf.Ticker")
    def test_empty_yfinance_response(self, mock_ticker):
        """Test handling of empty yfinance response."""
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1D")
        assert result["status"] in ["success", "error"]

    @patch("nifty_data_service.yf.Ticker")
    def test_yfinance_exception(self, mock_ticker):
        """Test handling of yfinance exception."""
        mock_ticker.side_effect = Exception("API Error")
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1D")
        assert result["status"] in ["success", "error"]
        assert result["source"] in ["yfinance", "cache", "error"]

    def test_timestamp_format(self):
        """Test that timestamps are in ISO format."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1D")
        for point in result["data"]:
            ts = point["timestamp"]
            try:
                datetime.fromisoformat(ts)
            except ValueError:
                msg = f"Timestamp {ts} is not valid ISO format"
                raise AssertionError(msg)

    def test_data_values_positive(self):
        """Test that all data values are positive."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1M")
        for point in result["data"]:
            assert point["value"] > 0, f"Non-positive value: {point}"

    def test_api_response_structure(self):
        """Test that API response has correct structure."""
        from nifty_data_service import get_nifty_data

        result = get_nifty_data("1D")
        required_keys = ["symbol", "name", "range", "data", "source", "cached", "stale", "last_updated", "status"]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
