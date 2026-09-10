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


"""Pytest configuration and shared fixtures for Indian Stock Tracker tests."""
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_yfinance_ticker():
    """Create a mock yfinance Ticker object with configurable history data."""
    mock_ticker = MagicMock()

    def create_history_data(dates, opens, highs, lows, closes, volumes):
        import pandas as pd

        hist_data = {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Adj Close": closes, "Volume": volumes}
        return pd.DataFrame(hist_data, index=pd.to_datetime(dates))

    mock_ticker.history.return_value = create_history_data(
        dates=["2024-01-01", "2024-01-02", "2024-01-03"],
        opens=[100.0, 101.0, 102.0],
        highs=[105.0, 106.0, 107.0],
        lows=[99.0, 100.0, 101.0],
        closes=[104.0, 105.0, 106.0],
        volumes=[1000000, 1100000, 1200000],
    )
    return mock_ticker


@pytest.fixture
def mock_nse_response():
    """Create a mock NSE API response."""
    return {
        "data": [
            {
                "symbol": "RELIANCE",
                "open": 2500.0,
                "high": 2550.0,
                "low": 2490.0,
                "close": 2530.0,
                "volume": 1000000,
                "date": "01-Jan-2024",
            },
            {
                "symbol": "TCS",
                "open": 3500.0,
                "high": 3550.0,
                "low": 3490.0,
                "close": 3530.0,
                "volume": 500000,
                "date": "01-Jan-2024",
            },
        ]
    }


@pytest.fixture
def mock_mfapi_response():
    """Create a mock mfapi.in response for mutual fund NAV data."""
    return {
        "meta": {
            "scheme_code": "120503",
            "scheme_name": "Test Fund - Direct Growth",
            "fund_house": "Test AMC",
            "scheme_type": "Open Ended",
            "scheme_category": "Large Cap Fund",
        },
        "data": [
            {"date": "01-01-2024", "nav": "100.50"},
            {"date": "02-01-2024", "nav": "101.00"},
            {"date": "03-01-2024", "nav": "101.50"},
        ],
    }


@pytest.fixture
def sample_ohlcv_data():
    """Sample OHLCV data for testing."""
    import datetime

    from data_sources import OHLCV

    return [
        OHLCV(
            date=datetime.date(2024, 1, 1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            adj_close=104.0,
            volume=1000000,
        ),
        OHLCV(
            date=datetime.date(2024, 1, 2),
            open=104.0,
            high=106.0,
            low=103.0,
            close=105.0,
            adj_close=105.0,
            volume=1100000,
        ),
        OHLCV(
            date=datetime.date(2024, 1, 3),
            open=105.0,
            high=107.0,
            low=104.0,
            close=106.0,
            adj_close=106.0,
            volume=1200000,
        ),
    ]


@pytest.fixture
def mock_tigzig_schemes():
    """Mock TigZig API response for scheme search."""
    return {
        "data": [
            {
                "scheme_code": "1001",
                "scheme_name": "Fund 1 - Direct Growth",
                "amc": "AMC 1",
                "category_sub": "Large Cap Fund",
            },
            {
                "scheme_code": "1002",
                "scheme_name": "Fund 2 - Direct Growth",
                "amc": "AMC 2",
                "category_sub": "Large Cap Fund",
            },
        ],
        "total": 2,
        "page": 1,
        "page_size": 100,
    }


@pytest.fixture
def mock_tigzig_nav():
    """Mock TigZig API response for NAV history."""
    return {
        "data": [
            {"nav": "100.00", "date": "01-01-2024"},
            {"nav": "101.00", "date": "02-01-2024"},
            {"nav": "102.00", "date": "03-01-2024"},
        ]
    }


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    from models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def flask_test_client():
    """Create a Flask test client with test configuration."""
    from flask_app import app

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# Pytest markers
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "api: API/Flask endpoint tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "external: Tests that require external API access")
