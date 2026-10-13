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


# -*- coding: utf-8 -*-
import unittest

from baseUnitTest import baseUnitTest
from nseta.common.symbols import get_index_constituents_list, get_symbol_list


class TestSymbols(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_symbol_list(self):
        df = get_symbol_list()
        # Check popular names are in the list
        _ril = df.loc[:, "SYMBOL"] == "RELIANCE"
        # Expect 1 row
        self.assertEqual(df[_ril].shape[0], 1)
        _sbi = df.loc[:, "SYMBOL"] == "SBIN"
        # Check company matches the expected value
        self.assertEqual(df[_sbi].iloc[0].get("NAME OF COMPANY"), "State Bank of India")

    def test_index_constituents_list(self):
        df = get_index_constituents_list("NIFTY50")
        # Check for 50 items
        self.assertEqual(df.shape[0], 50)

        # Check popular names are in the list
        _sbi = df.loc[:, "Symbol"] == "SBIN"
        # Check company matches the expected value
        self.assertEqual(df[_sbi].iloc[0].get("Company Name"), "State Bank of India")
        self.assertEqual(df[_sbi].iloc[0].get("Industry").upper(), "FINANCIAL SERVICES")

        df = get_index_constituents_list("NIFTYCPSE")
        # Check popular names are in the list
        _oil = df.loc[:, "Symbol"] == "OIL"
        # Check company matches the expected value
        self.assertEqual(df[_oil].iloc[0].get("ISIN Code"), "INE274J01014")

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSymbols)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if six.PY2:
        if result.wasSuccessful():
            print("tests OK")
        for test, error in result.errors:
            print(f"=========Error in: {test}===========")
            print(error)
            print("======================================")

        for test, failures in result.failures:
            print(f"=========Error in: {test}===========")
            print(failures)
            print("======================================")
