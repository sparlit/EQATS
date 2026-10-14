import datetime
import sys
import zoneinfo
from unittest.mock import MagicMock, patch

# Provide dummy pytz and sqlalchemy/tickerplot mocks before importing read_sql_data
class DummyPytz:
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

import modules.adapted.tickdownload.read_sql_data as read_sql_data


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

    with patch("modules.adapted.tickdownload.read_sql_data.create_or_get_all_scrips_table", return_value=mock_table), \
         patch("modules.adapted.tickdownload.read_sql_data.select_expr", return_value=mock_select), \
         patch("modules.adapted.tickdownload.read_sql_data.execute_one", return_value=mock_result) as mock_exec:

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

    with patch.object(read_sql_data, "_DB_METADATA", mock_global_meta), \
         patch("modules.adapted.tickdownload.read_sql_data.create_or_get_all_scrips_table", return_value=mock_table), \
         patch("modules.adapted.tickdownload.read_sql_data.select_expr", return_value=mock_select), \
         patch("modules.adapted.tickdownload.read_sql_data.execute_one", return_value=mock_result) as mock_exec:

        symbols = read_sql_data.get_all_scrips_names_in_db(metadata=None)
        assert symbols == ["INFY"]
        mock_exec.assert_called_once_with(mock_select.where.return_value, engine=mock_global_meta.bind)


def test_get_hist_data_as_dataframes_dict_fallback():
    mock_meta = MagicMock()
    mock_meta.bind = MagicMock()

    with patch.object(read_sql_data, "_DB_METADATA", mock_meta), \
         patch("modules.adapted.tickdownload.read_sql_data.get_all_scrips_names_in_db", return_value=["RELIANCE"]) as mock_get_scrips, \
         patch("modules.adapted.tickdownload.read_sql_data.create_or_get_nse_equities_hist_data", return_value=MagicMock()), \
         patch("pandas.io.sql.read_sql") as mock_read_sql:

        import pandas as pd
        mock_df = pd.DataFrame({
            "date": [datetime.datetime(2025, 1, 1)],
            "open": [100],
            "high": [105],
            "low": [95],
            "close": [102],
            "volume": [1000],
            "delivery": [500]
        })
        mock_read_sql.return_value = mock_df

        result = read_sql_data.get_hist_data_as_dataframes_dict(metadata=None, max_scrips=1)
        assert "RELIANCE" in result
        mock_get_scrips.assert_called_once_with(metadata=mock_meta)


def test_main():
    mock_meta = MagicMock()
    with patch("modules.adapted/tickdownload/read_sql_data.get_metadata", return_value=mock_meta) if False else \
         patch("modules.adapted.tickdownload.read_sql_data.get_metadata", return_value=mock_meta), \
         patch("modules.adapted.tickdownload.read_sql_data.get_hist_data_as_dataframes_dict") as mock_get_hist:

        args = ["read_sql_data.py", "--dbpath", "sqlite:///test.db"]
        with patch("sys.argv", args):
            res = read_sql_data.main(args)
            assert res == 0
            mock_get_hist.assert_called_once_with(metadata=mock_meta)
