"""Unit tests for modules/adapted/tickdownload/read_sql_data.py."""

# pylint: disable=missing-class-docstring, missing-function-docstring
# codespell:ignore

import datetime
import sys
import zoneinfo
from unittest.mock import MagicMock, patch

import pandas as pd


# Provide dummy pytz and sqlalchemy/tickerplot mocks before importing read_sql_data
class DummyPytz:
    """Dummy pytz replacement using zoneinfo."""

    __name__ = "pytz"
    __version__ = "2024.1"
    UTC = datetime.timezone.utc
    utc = datetime.timezone.utc

    @staticmethod
    def timezone(tz):
        return zoneinfo.ZoneInfo(tz)


sys.modules.setdefault("pytz", DummyPytz)
sys.modules.setdefault("sqlalchemy", MagicMock())
sys.modules.setdefault("tickerplot", MagicMock())
sys.modules.setdefault("tickerplot.sql", MagicMock())
sys.modules.setdefault("tickerplot.sql.sqlalchemy_wrapper", MagicMock())

import modules.adapted.tickdownload.read_sql_data as read_sql_data  # noqa: E402


def test_is_ist_market_session_active():
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")

    # Mon 10:00 AM IST -> active
    mon_10am = datetime.datetime(2025, 1, 13, 10, 0, tzinfo=ist)
    assert read_sql_data.is_ist_market_session_active(mon_10am) is True

    # Sat 10:00 AM IST -> inactive
    sat_10am = datetime.datetime(2025, 1, 18, 10, 0, tzinfo=ist)
    assert read_sql_data.is_ist_market_session_active(sat_10am) is False


def test_round_to_ist_tick():
    assert read_sql_data.round_to_ist_tick(100.02) == 100.0
    assert read_sql_data.round_to_ist_tick(100.03) == 100.05
    assert read_sql_data.round_to_ist_tick(-5.0) == 0.0


def test_get_all_scrips_names_in_db_with_metadata():
    mock_meta = MagicMock()
    mock_meta.bind = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("RELIANCE",), ("TCS",)]

    patch_table = patch(
        "modules.adapted.tickdownload.read_sql_data.create_or_get_all_scrips_table",
        return_value=mock_table,
    )
    patch_select = patch(
        "modules.adapted.tickdownload.read_sql_data.select_expr",
        return_value=mock_select,
    )
    patch_exec = patch(
        "modules.adapted.tickdownload.read_sql_data.execute_one",
        return_value=mock_result,
    )

    with patch_table, patch_select, patch_exec as mock_exec:
        symbols = read_sql_data.get_all_scrips_names_in_db(metadata=mock_meta)
        assert symbols == ["RELIANCE", "TCS"]
        mock_exec.assert_called_once_with(mock_select.where.return_value, engine=mock_meta.bind)


def test_get_all_scrips_names_in_db_fallback_to_global_metadata():
    mock_global_meta = MagicMock()
    mock_global_meta.bind = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("INFY",)]

    patch_global = patch.object(read_sql_data, "_DB_METADATA", mock_global_meta)
    patch_table = patch(
        "modules.adapted.tickdownload.read_sql_data.create_or_get_all_scrips_table",
        return_value=mock_table,
    )
    patch_select = patch(
        "modules.adapted.tickdownload.read_sql_data.select_expr",
        return_value=mock_select,
    )
    patch_exec = patch(
        "modules.adapted.tickdownload.read_sql_data.execute_one",
        return_value=mock_result,
    )

    with patch_global, patch_table, patch_select, patch_exec as mock_exec:
        symbols = read_sql_data.get_all_scrips_names_in_db(metadata=None)
        assert symbols == ["INFY"]
        mock_exec.assert_called_once_with(
            mock_select.where.return_value, engine=mock_global_meta.bind
        )


def test_get_hist_data_as_dataframes_dict_fallback():
    mock_meta = MagicMock()
    mock_meta.bind = MagicMock()

    patch_global = patch.object(read_sql_data, "_DB_METADATA", mock_meta)
    patch_scrips = patch(
        "modules.adapted.tickdownload.read_sql_data.get_all_scrips_names_in_db",
        return_value=["RELIANCE"],
    )
    patch_hist = patch(
        "modules.adapted.tickdownload.read_sql_data.create_or_get_nse_equities_hist_data",
        return_value=MagicMock(),
    )
    patch_sql = patch("pandas.io.sql.read_sql")

    with patch_global, patch_scrips as mock_get_scrips, patch_hist, patch_sql as mock_read_sql:
        mock_df = pd.DataFrame(
            {
                "date": [datetime.datetime(2025, 1, 1)],
                "open": [100],
                "high": [105],
                "low": [95],
                "close": [102],
                "volume": [1000],
                "delivery": [500],
            }
        )
        mock_read_sql.return_value = mock_df

        result = read_sql_data.get_hist_data_as_dataframes_dict(metadata=None, max_scrips=1)
        assert "RELIANCE" in result
        mock_get_scrips.assert_called_once_with(metadata=mock_meta)


def test_main():
    mock_meta = MagicMock()
    patch_get_meta = patch(
        "modules.adapted.tickdownload.read_sql_data.get_metadata",
        return_value=mock_meta,
    )
    patch_get_hist = patch(
        "modules.adapted.tickdownload.read_sql_data.get_hist_data_as_dataframes_dict"
    )

    with patch_get_meta, patch_get_hist as mock_get_hist:
        args = ["read_sql_data.py", "--dbpath", "sqlite:///test.db"]
        res = read_sql_data.main(args)
        assert res == 0
        mock_get_hist.assert_called_once_with(metadata=mock_meta)
