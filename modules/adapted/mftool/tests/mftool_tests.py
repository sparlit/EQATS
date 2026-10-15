"""This is a test module for testing mftool functionality."""

import datetime
import json
import logging
import unittest
import zoneinfo
from unittest.mock import patch

import six
from mftool import Mftool
from mftool.utils import get_friday, get_today, is_holiday

log = logging.getLogger("mftool")
logging.basicConfig(level=logging.DEBUG)


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
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


class TestAPIs(unittest.TestCase):
    def setUp(self):
        self.mftool = Mftool()

    def test_get_scheme_codes(self):
        sc = self.mftool.get_scheme_codes()
        self.assertIsNotNone(sc)
        self.assertIsInstance(sc, dict)
        # test the json format return
        sc_json = self.mftool.get_scheme_codes(as_json=True)
        self.assertIsInstance(sc_json, str)
        # reconstruct the dict from json and compare
        six.assertCountEqual(self, sc, json.loads(sc_json))
        result = self.mftool.get_available_schemes("ICICI")
        self.assertNotIn(result[next(iter(result))], "Axis")

    def test_is_valid_code(self):
        code = "119598"
        self.assertTrue(self.mftool.is_valid_code(code))

    def test_negative_is_valid_code(self):
        wrong_code = "1195"
        self.assertFalse(self.mftool.is_valid_code(wrong_code))

    def test_get_scheme_quote(self):
        code = "101305"
        self.assertIsInstance(self.mftool.get_scheme_quote(code), dict)
        # with json respomftool
        self.assertIsInstance(self.mftool.get_scheme_quote(code, as_json=True), str)
        # with wrong code
        code = "wrong code"
        self.assertIsNone(self.mftool.get_scheme_quote(code))
        # with code in 'int' format
        code = 101305
        self.assertIsInstance(self.mftool.get_scheme_quote(code), dict)
        # verify data present
        result = self.mftool.get_scheme_quote(code)
        self.assertIsNotNone(result)

    def test_get_scheme_historical_nav(self):
        code = "101305"
        self.assertIsInstance(self.mftool.get_scheme_historical_nav(code), dict)
        # with json respomftool
        self.assertIsInstance(self.mftool.get_scheme_historical_nav(code, as_json=True), str)
        # with wrong code
        code = "wrong code"
        self.assertIsNone(self.mftool.get_scheme_historical_nav(code))
        # with code in 'int' format
        code = 101305
        self.assertIsInstance(self.mftool.get_scheme_historical_nav(code), dict)
        # verify data present
        result = self.mftool.get_scheme_historical_nav(code)
        self.assertIsNotNone(result)

    def test_get_scheme_details(self):
        code = "101305"
        self.assertIsInstance(self.mftool.get_scheme_details(code), dict)
        # with json respomftool
        self.assertIsInstance(self.mftool.get_scheme_details(code, as_json=True), str)
        # with wrong code
        code = "wrong code"
        self.assertIsNone(self.mftool.get_scheme_details(code))
        # with code in 'int' format
        code = 101305
        self.assertIsInstance(self.mftool.get_scheme_details(code), dict)
        # verify data present
        result = self.mftool.get_scheme_details(code)
        self.assertIsNotNone(result)

    def test_calculate_balance_units_value(self):
        code = "101305"
        result = self.mftool.calculate_balance_units_value(code, 221)
        self.assertIsNotNone(result)

    def test_get_scheme_historical_nav_year(self):
        code = "101305"
        self.assertIsInstance(self.mftool.get_scheme_historical_nav_year(code, 2018), dict)
        # with json respomftool
        self.assertIsInstance(
            self.mftool.get_scheme_historical_nav_year(code, 2018, as_json=True), str
        )
        # with wrong code
        code = "wrong code"
        self.assertIsNone(self.mftool.get_scheme_historical_nav_year(code, 2018))
        # with code in 'int' format
        code = 101305
        self.assertIsInstance(self.mftool.get_scheme_historical_nav_year(code, 2018), dict)
        # verify data present
        result = self.mftool.get_scheme_historical_nav_year(code, 2018)
        self.assertIsNotNone(result)

    def test_get_day(self):
        if is_holiday():
            self.assertTrue(get_friday())
        else:
            self.assertTrue(get_today())

    def test_get_scheme_historical_nav_for_dates(self):
        code = "101305"
        self.assertIsInstance(
            self.mftool.get_scheme_historical_nav_for_dates(code, "1-1-2018", "31-12-2018"), dict
        )
        # with json respomftool
        self.assertIsInstance(
            self.mftool.get_scheme_historical_nav_for_dates(
                code, "1-1-2018", "31-12-2018", as_json=True
            ),
            str,
        )
        # with wrong code
        code = "wrong code"
        self.assertIsNone(
            self.mftool.get_scheme_historical_nav_for_dates(code, "1-1-2018", "31-12-2018")
        )
        # with code in 'int' format
        code = 101305
        self.assertIsInstance(
            self.mftool.get_scheme_historical_nav_for_dates(code, "1-1-2018", "31-12-2018"), dict
        )
        # verify data present
        result = self.mftool.get_scheme_historical_nav_for_dates(code, "1-1-2018", "31-12-2018")
        self.assertIsNotNone(result)

    def test_get_open_ended_equity_scheme_performance(self):
        self.assertIsInstance(self.mftool.get_open_ended_equity_scheme_performance(False), dict)
        # verify data present
        result = self.mftool.get_open_ended_equity_scheme_performance(False)
        self.assertNotEqual(
            result,
            {
                "Large Cap": [],
                "Large & Mid Cap": [],
                "Multi Cap": [],
                "Mid Cap": [],
                "Small Cap": [],
                "Value": [],
                "ELSS": [],
                "Contra": [],
                "Dividend Yield": [],
                "Focused": [],
            },
        )

    def test_get_open_ended_debt_scheme_performance(self):
        with patch.object(
            self.mftool,
            "_get_daily_scheme_performance",
            return_value=[{"scheme_name": "Debt Fund"}],
        ):
            res = self.mftool.get_open_ended_debt_scheme_performance()
            self.assertIsInstance(res, dict)

    def test_get_open_ended_hybrid_scheme_performance(self):
        with patch.object(
            self.mftool,
            "_get_daily_scheme_performance",
            return_value=[{"scheme_name": "Hybrid Fund"}],
        ):
            res = self.mftool.get_open_ended_hybrid_scheme_performance()
            self.assertIsInstance(res, dict)

    def test_get_open_ended_solution_scheme_performance(self):
        with patch.object(
            self.mftool,
            "_get_daily_scheme_performance",
            return_value=[{"scheme_name": "Solution Fund"}],
        ):
            res = self.mftool.get_open_ended_solution_scheme_performance()
            self.assertIsInstance(res, dict)

    def test_get_open_ended_other_scheme_performance(self):
        with patch.object(
            self.mftool,
            "_get_daily_scheme_performance",
            return_value=[{"scheme_name": "Other Fund"}],
        ):
            res = self.mftool.get_open_ended_other_scheme_performance()
            self.assertIsInstance(res, dict)

    def test_calculate_returns(self):
        code = "101305"
        with patch.object(self.mftool, "get_scheme_quote", return_value={"nav": "50.0"}):
            res = self.mftool.calculate_returns(
                code, balanced_units=1000, monthly_sip=1000, investment_in_months=12
            )
            self.assertIsInstance(res, dict)
            self.assertIn("final_investment_value", res)

        invalid_res = self.mftool.calculate_returns("invalid_code", 1000, 1000, 12)
        self.assertIsNone(invalid_res)

    def test_search_schemes(self):
        mock_codes = {
            "101305": "HDFC Top 100 Fund - Direct Plan - Growth",
            "119598": "Axis Bluechip Fund - Direct Plan - Growth",
        }
        with patch.object(self.mftool, "get_scheme_codes", return_value=mock_codes):
            results = self.mftool.search_schemes("HDFC", limit=5)
            self.assertIsInstance(results, list)
            self.assertTrue(len(results) > 0)
            self.assertEqual(results[0]["code"], "101305")

            empty_res = self.mftool.search_schemes("")
            self.assertEqual(empty_res, [])

    def test_search_schemes_by_amc(self):
        mock_schemes = {"101305": "HDFC Equity Fund - Direct"}
        with patch.object(self.mftool, "get_available_schemes", return_value=mock_schemes):
            results = self.mftool.search_schemes_by_amc("HDFC", search_term="Equity")
            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 1)

            results_no_search = self.mftool.search_schemes_by_amc("HDFC")
            self.assertIsInstance(results_no_search, list)

    def test_search_schemes_by_type(self):
        mock_codes = {
            "101305": "HDFC Equity Growth Fund",
            "119598": "Axis Debt Savings Fund",
        }
        with patch.object(self.mftool, "get_scheme_codes", return_value=mock_codes):
            results = self.mftool.search_schemes_by_type("Equity")
            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["code"], "101305")

    def test_get_bulk_quotes(self):
        mock_quote = {"scheme_code": "101305", "nav": "50.0", "scheme_name": "Test Fund"}
        with (
            patch.object(self.mftool, "is_valid_code", return_value=True),
            patch.object(self.mftool, "get_scheme_quote", return_value=mock_quote),
        ):
            quotes = self.mftool.get_bulk_quotes(["101305"])
            self.assertIsInstance(quotes, dict)
            self.assertIn("101305", quotes)

    def test_calculate_portfolio_value(self):
        mock_quotes = {
            "101305": {"nav": "50.0", "scheme_name": "Test Fund", "last_updated": "01-Jan-2025"}
        }
        holdings = [{"scheme_code": "101305", "units": 100}]
        with patch.object(self.mftool, "get_bulk_quotes", return_value=mock_quotes):
            portfolio = self.mftool.calculate_portfolio_value(holdings)
            self.assertIsInstance(portfolio, dict)
            self.assertEqual(portfolio["total_value"], 5000.0)

    def test_cache_management(self):
        self.mftool.clear_cache()
        stats = self.mftool.get_cache_stats()
        self.assertIsInstance(stats, dict)
        self.mftool.disable_cache()
        self.mftool.enable_cache()

    def test_ist_market_helpers(self):
        self.assertEqual(round_to_ist_tick(100.03), 100.05)
        self.assertEqual(round_to_ist_tick(-5.0), 0.0)

        # Monday 10:00 AM IST
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        mon_open = datetime.datetime(2025, 1, 6, 10, 0, tzinfo=ist)
        self.assertTrue(is_ist_market_session_active(mon_open))

        # Sunday 10:00 AM IST
        sun_closed = datetime.datetime(2025, 1, 5, 10, 0, tzinfo=ist)
        self.assertFalse(is_ist_market_session_active(sun_closed))


if __name__ == "__main__":
    unittest.main()
