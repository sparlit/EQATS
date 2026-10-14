"""
Unit tests for modules/adapted/tickdownload/read_sql_data.py
Verifies metadata validation, fallback handling, IST market session check, and tick rounding.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock sqlalchemy and tickerplot before importing read_sql_data
mock_sqla = MagicMock()
mock_tickerplot_wrapper = MagicMock()

sys.modules.setdefault("sqlalchemy", mock_sqla)
sys.modules.setdefault("tickerplot", MagicMock())
sys.modules.setdefault("tickerplot.sql", MagicMock())
sys.modules.setdefault("tickerplot.sql.sqlalchemy_wrapper", mock_tickerplot_wrapper)

# Add modules/adapted/tickdownload to path for import compatibility
tickdownload_dir = str(Path(__file__).resolve().parent.parent / "modules" / "adapted" / "tickdownload")
if tickdownload_dir not in sys.path:
    sys.path.insert(0, tickdownload_dir)

import modules.adapted.tickdownload.read_sql_data as read_sql_data  # noqa: E402


def setup_function():
    """Reset global _DB_METADATA before each test."""
    read_sql_data._DB_METADATA = None


def teardown_function():
    """Reset global _DB_METADATA after each test."""
    read_sql_data._DB_METADATA = None


def test_get_all_scrips_names_in_db_raises_value_error_when_no_metadata():
    """Test that get_all_scrips_names_in_db raises ValueError when metadata and _DB_METADATA are None."""
    read_sql_data._DB_METADATA = None
    with pytest.raises(ValueError, match="Database metadata must be provided or set via _DB_METADATA"):
        read_sql_data.get_all_scrips_names_in_db(metadata=None)


def test_get_hist_data_as_dataframes_dict_raises_value_error_when_no_metadata():
    """Test that get_hist_data_as_dataframes_dict raises ValueError when metadata and _DB_METADATA are None."""
    read_sql_data._DB_METADATA = None
    with pytest.raises(ValueError, match="Database metadata must be provided or set via _DB_METADATA"):
        read_sql_data.get_hist_data_as_dataframes_dict(metadata=None)


def test_get_all_scrips_names_in_db_uses_global_db_metadata():
    """Test that get_all_scrips_names_in_db falls back to _DB_METADATA when metadata is None."""
    mock_metadata = MagicMock()
    read_sql_data._DB_METADATA = mock_metadata

    mock_table = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("SBIN",), ("RELIANCE",)]

    with (
        patch("modules.adapted.tickdownload.read_sql_data.create_or_get_all_scrips_table", return_value=mock_table),
        patch("modules.adapted.tickdownload.read_sql_data.execute_one", return_value=mock_result),
    ):
        symbols = read_sql_data.get_all_scrips_names_in_db()
        assert symbols == ["SBIN", "RELIANCE"]


def test_get_hist_data_as_dataframes_dict_uses_global_db_metadata():
    """Test that get_hist_data_as_dataframes_dict falls back to _DB_METADATA when metadata is None."""
    mock_metadata = MagicMock()
    mock_metadata.bind = MagicMock()
    read_sql_data._DB_METADATA = mock_metadata

    import pandas as pd

    df = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-01")],
        "open": [100.0],
        "high": [105.0],
        "low": [99.0],
        "close": [104.0],
        "volume": [1000],
        "delivery": [500],
    })

    with (
        patch("modules.adapted.tickdownload.read_sql_data.get_all_scrips_names_in_db", return_value=["SBIN"]),
        patch("modules.adapted.tickdownload.read_sql_data.create_or_get_nse_equities_hist_data", return_value=MagicMock()),
        patch("pandas.io.sql.read_sql", return_value=df),
    ):
        res = read_sql_data.get_hist_data_as_dataframes_dict()
        assert "SBIN" in res


def test_is_ist_market_session_active():
    """Test IST market session active check."""
    import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    # A weekday at 10:00 AM IST
    weekday_active = datetime.datetime(2025, 1, 15, 10, 0, 0, tzinfo=ist)
    assert read_sql_data.is_ist_market_session_active(weekday_active) is True

    # A weekend (Saturday)
    weekend_dt = datetime.datetime(2025, 1, 18, 10, 0, 0, tzinfo=ist)
    assert read_sql_data.is_ist_market_session_active(weekend_dt) is False


def test_round_to_ist_tick():
    """Test tick rounding function."""
    assert read_sql_data.round_to_ist_tick(100.03) == 100.05
    assert read_sql_data.round_to_ist_tick(100.02) == 100.00
    assert read_sql_data.round_to_ist_tick(-5.0) == 0.0


def test_main_with_invalid_dbpath():
    """Test main function with an invalid dbpath."""
    with patch("modules.adapted.tickdownload.read_sql_data.get_metadata", side_effect=Exception("Connection failed")):
        ret = read_sql_data.main(["--dbpath", "invalid_db_path"])
        assert ret == -1
