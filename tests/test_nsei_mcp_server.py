import datetime
import unittest
from unittest.mock import patch

import pandas as pd
import pytz

from modules.adapted.nsei_mcp_server.nsei_mcp_server import (
    _get_data_for_date_range,
    clear_trades_cache,
    get_cached_trades,
    get_top_movers,
    get_trades,
    is_ist_market_session_active,
    round_to_ist_tick,
)


class TestNSEIMCPServer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_trades_cache()

    def tearDown(self):
        clear_trades_cache()

    def test_round_to_ist_tick(self):
        self.assertEqual(round_to_ist_tick(0.0), 0.0)
        self.assertEqual(round_to_ist_tick(-5.0), 0.0)
        self.assertEqual(round_to_ist_tick(100.02), 100.0)
        self.assertEqual(round_to_ist_tick(100.03), 100.05)
        self.assertEqual(round_to_ist_tick(100.07), 100.05)
        self.assertEqual(round_to_ist_tick(100.08), 100.10)

    def test_is_ist_market_session_active(self):
        ist = pytz.timezone("Asia/Kolkata")
        # Saturday: inactive
        saturday = datetime.datetime(2025, 4, 12, 11, 0, 0, tzinfo=ist)
        self.assertFalse(is_ist_market_session_active(saturday))

        # Monday during market hours
        monday_market_hours = datetime.datetime(2025, 4, 14, 10, 30, 0, tzinfo=ist)
        self.assertTrue(is_ist_market_session_active(monday_market_hours))

        # Monday outside market hours
        monday_after_hours = datetime.datetime(2025, 4, 14, 16, 0, 0, tzinfo=ist)
        self.assertFalse(is_ist_market_session_active(monday_after_hours))

    def test_trades_cache_lifecycle(self):
        self.assertTrue(get_cached_trades().empty)

        mock_df = pd.DataFrame(
            [
                {
                    "TradDt": "2025-04-11",
                    "SctySrs": "EQ",
                    "TckrSymb": "RELIANCE",
                    "OpnPric": 2500.0,
                    "HghPric": 2550.0,
                    "LwPric": 2490.0,
                    "ClsPric": 2540.0,
                    "TtlTradgVol": 100000,
                    "TtlTrfVal": 250000000.0,
                }
            ]
        )

        with patch(
            "modules.adapted.nsei_mcp_server.nsei_mcp_server._download_bhav_copy",
            return_value=mock_df,
        ) as mock_download:
            # First fetch: cache miss
            df1 = _get_data_for_date_range("2025-04-11", 1)
            self.assertIsNotNone(df1)
            self.assertEqual(len(df1), 1)
            self.assertEqual(mock_download.call_count, 1)

            # Global trades cache should now contain 1 record
            cached = get_cached_trades()
            self.assertEqual(len(cached), 1)
            self.assertEqual(cached["TckrSymb"].iloc[0], "RELIANCE")

            # Second fetch for same date: cache hit (no additional download call)
            df2 = _get_data_for_date_range("2025-04-11", 1)
            self.assertIsNotNone(df2)
            self.assertEqual(len(df2), 1)
            self.assertEqual(mock_download.call_count, 1)

        # Clear cache
        clear_trades_cache()
        self.assertTrue(get_cached_trades().empty)

    async def test_get_trades_tool(self):
        mock_df = pd.DataFrame(
            [
                {
                    "TradDt": "2025-04-11",
                    "SctySrs": "EQ",
                    "TckrSymb": "INFY",
                    "OpnPric": 1400.0,
                    "HghPric": 1420.0,
                    "LwPric": 1390.0,
                    "ClsPric": 1415.0,
                    "TtlTradgVol": 50000,
                    "TtlTrfVal": 70000000.0,
                },
                {
                    "TradDt": "2025-04-11",
                    "SctySrs": "EQ",
                    "TckrSymb": "TCS",
                    "OpnPric": 3500.0,
                    "HghPric": 3550.0,
                    "LwPric": 3480.0,
                    "ClsPric": 3520.0,
                    "TtlTradgVol": 30000,
                    "TtlTrfVal": 105000000.0,
                },
            ]
        )

        with patch(
            "modules.adapted.nsei_mcp_server.nsei_mcp_server._download_bhav_copy",
            return_value=mock_df,
        ):
            res_all = await get_trades("2025-04-11", ndays=1)
            self.assertIn("trades", res_all)
            self.assertEqual(len(res_all["trades"]), 2)

            res_infy = await get_trades("2025-04-11", ndays=1, symbol="INFY")
            self.assertIn("trades", res_infy)
            self.assertEqual(len(res_infy["trades"]), 1)
            self.assertEqual(res_infy["trades"][0]["TckrSymb"], "INFY")

    async def test_get_top_movers_tool(self):
        mock_df = pd.DataFrame(
            [
                {
                    "TradDt": "2025-04-11",
                    "SctySrs": "EQ",
                    "TckrSymb": "GAINER_STK",
                    "OpnPric": 100.0,
                    "HghPric": 115.0,
                    "LwPric": 99.0,
                    "ClsPric": 110.0,
                    "TtlTradgVol": 20000,
                    "TtlTrfVal": 2200000.0,
                },
                {
                    "TradDt": "2025-04-11",
                    "SctySrs": "EQ",
                    "TckrSymb": "LOSER_STK",
                    "OpnPric": 100.0,
                    "HghPric": 101.0,
                    "LwPric": 88.0,
                    "ClsPric": 90.0,
                    "TtlTradgVol": 15000,
                    "TtlTrfVal": 1350000.0,
                },
            ]
        )

        with patch(
            "modules.adapted.nsei_mcp_server.nsei_mcp_server._download_bhav_copy",
            return_value=mock_df,
        ):
            res = await get_top_movers("2025-04-11", ndays=1)
            self.assertIn("top_gainers", res)
            self.assertIn("top_losers", res)
            self.assertEqual(len(res["top_gainers"]), 1)
            self.assertEqual(res["top_gainers"][0]["TckrSymb"], "GAINER_STK")
            self.assertEqual(len(res["top_losers"]), 1)
            self.assertEqual(res["top_losers"][0]["TckrSymb"], "LOSER_STK")


if __name__ == "__main__":
    unittest.main()
