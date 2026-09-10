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


"""Unit tests for data_sources module."""
import datetime
from unittest.mock import MagicMock, patch

import pytest
from data_sources import (
    OHLCV,
    DataSource,
    MutualFundSource,
    NSESource,
    YFinanceSource,
    _strip_exchange_suffix,
    fetch_with_fallback,
    resolve_name,
)


def test_strip_exchange_suffix():
    """Test stripping exchange suffix from symbols."""
    assert _strip_exchange_suffix("RELIANCE.NS") == "RELIANCE"
    assert _strip_exchange_suffix("TCS.BO") == "TCS"
    assert _strip_exchange_suffix("INFY") == "INFY"
    assert _strip_exchange_suffix("HDFC.NS") == "HDFC"


class TestOHLCV:
    def test_ohlcv_creation(self):
        test_date = datetime.date(2024, 1, 1)
        ohlcv = OHLCV(date=test_date, open=100.0, high=105.0, low=99.0, close=104.0, adj_close=104.0, volume=1000000)
        assert ohlcv.date == test_date
        assert ohlcv.open == 100.0
        assert ohlcv.close == 104.0
        assert ohlcv.volume == 1000000


class TestDataSourceAbstract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            DataSource()


class TestYFinanceSource:
    @patch("yfinance.Ticker")
    def test_fetch_latest_success(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_row = MagicMock()
        mock_row.name = datetime.datetime(2024, 1, 1)
        mock_row.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "Open": 100.0,
                "High": 105.0,
                "Low": 99.0,
                "Close": 104.0,
                "Adj Close": 104.0,
                "Volume": 1000000.0,
            }.get(k, 0.0)
        )
        mock_hist.iloc.__getitem__ = MagicMock(return_value=mock_row)
        mock_ticker.history.return_value = mock_hist
        mock_ticker_class.return_value = mock_ticker

        source = YFinanceSource()
        result = source.fetch_latest("RELIANCE.NS")

        assert result is not None
        assert isinstance(result, OHLCV)
        assert result.date == datetime.date(2024, 1, 1)
        mock_ticker.history.assert_called_once_with(period="5d")

    @patch("yfinance.Ticker")
    def test_fetch_latest_empty(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = None
        mock_ticker_class.return_value = mock_ticker
        source = YFinanceSource()
        result = source.fetch_latest("BAD.SYMBOL")
        assert result is None

    @patch("yfinance.Ticker")
    def test_fetch_latest_exception(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("Network error")
        mock_ticker_class.return_value = mock_ticker
        source = YFinanceSource()
        result = source.fetch_latest("RELIANCE.NS")
        assert result is None


class TestNSESource:
    @patch("nsepy.get_history")
    def test_fetch_latest_success(self, mock_get_history):
        mock_hist = MagicMock()
        mock_row = MagicMock()
        mock_row.name = datetime.date(2024, 1, 1)
        mock_row.__getitem__ = MagicMock(
            side_effect=lambda k: {
                "Open": 2500.0,
                "High": 2550.0,
                "Low": 2490.0,
                "Close": 2530.0,
                "Volume": 1000000.0,
            }.get(k, 0.0)
        )
        mock_hist.iloc.__getitem__ = MagicMock(return_value=mock_row)
        mock_get_history.return_value = mock_hist

        source = NSESource()
        result = source.fetch_latest("RELIANCE")

        assert result is not None
        assert isinstance(result, OHLCV)
        assert result.date == datetime.date(2024, 1, 1)
        assert result.open == 2500.0
        assert result.high == 2550.0
        assert result.low == 2490.0
        assert result.close == 2530.0
        assert result.volume == 1000000

    @patch("nsepy.get_history")
    def test_fetch_latest_no_data(self, mock_get_history):
        mock_get_history.return_value = None
        source = NSESource()
        result = source.fetch_latest("INVALID")
        assert result is None

    @patch("nsepy.get_history")
    def test_fetch_latest_exception(self, mock_get_history):
        mock_get_history.side_effect = Exception("API error")
        source = NSESource()
        result = source.fetch_latest("RELIANCE")
        assert result is None

    @patch("nsepy.get_quote")
    def test_fetch_name_success(self, mock_get_quote):
        mock_get_quote.return_value = {"companyName": "Reliance Industries Ltd"}
        source = NSESource()
        name = source.fetch_name("RELIANCE")
        assert name == "Reliance Industries Ltd"


class TestMutualFundSource:
    @patch("requests.get")
    def test_fetch_latest_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "meta": {"scheme_name": "Test Fund"},
            "data": [{"nav": "100.50", "date": "01-01-2024"}],
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        source = MutualFundSource()
        result = source.fetch_latest("120503")
        assert result is not None
        assert isinstance(result, OHLCV)
        assert result.date == datetime.date(2024, 1, 1)
        assert result.open == 100.50
        assert result.volume == 0.0

    @patch("requests.get")
    def test_fetch_latest_no_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        source = MutualFundSource()
        result = source.fetch_latest("INVALID")
        assert result is None

    @patch("requests.get")
    def test_fetch_name_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"meta": {"scheme_name": "Test Fund"}}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        source = MutualFundSource()
        name = source.fetch_name("120503")
        assert name == "Test Fund"

    @patch("requests.get")
    def test_fetch_history_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"nav": "100.50", "date": "01-01-2024"},
                {"nav": "101.00", "date": "02-01-2024"},
                {"nav": "101.50", "date": "03-01-2024"},
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        source = MutualFundSource()
        history = source.fetch_history("120503", limit=2)
        assert len(history) == 2
        assert all(isinstance(item, OHLCV) for item in history)


class TestFetchWithFallback:
    @patch("data_sources.YFinanceSource.fetch_latest")
    @patch("data_sources.NSESource.fetch_latest")
    def test_nse_success(self, mock_yf, mock_nse):
        mock_nse.return_value = OHLCV(
            date=datetime.date(2024, 1, 1),
            open=2500.0,
            high=2550.0,
            low=2490.0,
            close=2530.0,
            adj_close=2530.0,
            volume=1000000,
        )
        mock_yf.return_value = None
        result = fetch_with_fallback("RELIANCE.NS")
        assert result is not None
        assert result.open == 2500.0

    @patch("data_sources.YFinanceSource.fetch_latest")
    @patch("data_sources.NSESource.fetch_latest")
    def test_yfinance_fallback(self, mock_yf, mock_nse):
        mock_nse.return_value = None
        mock_yf.return_value = OHLCV(
            date=datetime.date(2024, 1, 1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            adj_close=104.0,
            volume=1000000,
        )
        result = fetch_with_fallback("RELIANCE.NS")
        assert result is not None
        assert result.open == 100.0

    @patch("data_sources.YFinanceSource.fetch_latest")
    @patch("data_sources.NSESource.fetch_latest")
    def test_all_fail(self, mock_yf, mock_nse):
        mock_nse.return_value = None
        mock_yf.return_value = None
        result = fetch_with_fallback("INVALID.SYMBOL")
        assert result is None


class TestResolveName:
    @patch("data_sources.YFinanceSource.fetch_name")
    @patch("data_sources.NSESource.fetch_name")
    def test_nse_success(self, mock_yf, mock_nse):
        mock_nse.return_value = "Reliance Industries Limited"
        mock_yf.return_value = None
        name = resolve_name("RELIANCE.NS")
        assert name == "Reliance Industries Limited"

    @patch("data_sources.YFinanceSource.fetch_name")
    @patch("data_sources.NSESource.fetch_name")
    def test_all_fail(self, mock_yf, mock_nse):
        mock_nse.return_value = None
        mock_yf.return_value = None
        name = resolve_name("INVALID")
        assert name is None
