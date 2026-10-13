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
    This is a test module for testing
"""
import json
import logging
import unittest

import six
from mftool import Mftool
from mftool.utils import get_friday, get_today, is_holiday

log = logging.getLogger("mftool")
logging.basicConfig(level=logging.DEBUG)


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


# ToDO : Add remaining test

if __name__ == "__main__":
    unittest.main()
