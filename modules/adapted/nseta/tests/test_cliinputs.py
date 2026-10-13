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
from nseta.cli.inputs import *
from nseta.cli.livecli import live_quote


class TestCliInputs(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_validate_inputs(self):
        result = validate_inputs("2020-01-01", "2021-01-08", "SOMESYMBOL", strategy="rsi")
        self.assertTrue(result)

    def test_date_diff_strategy(self):
        result = validate_inputs("2020-12-25", "2021-01-07", "SOMESYMBOL", strategy="rsi")
        self.assertFalse(result)
        self.assertIn(
            "Please provide start and end date with a time delta of at least 20 days for the selected strategy.",
            self.capturedOutput.getvalue(),
        )

    def test_date_input_format(self):
        # with self.assertRaises(ValueError):
        result = validate_inputs("15-12-2020", "20-01-2020", "SOMESYMBOL", strategy="rsi")
        self.assertFalse(result)
        self.assertIn(
            "Please provide start and end date in format yyyy-mm-dd", self.capturedOutput.getvalue()
        )

    def test_print_help_msg(self):
        print_help_msg(live_quote)
        self.assertIn("Usage:  [OPTIONS]", self.capturedOutput.getvalue())

    def test_validate_symbol(self):
        result = validate_symbol("SOMESYMBOL")
        self.assertTrue(result)
        result = validate_symbol(None)
        self.assertFalse(result)
        self.assertIn("Please provide security", self.capturedOutput.getvalue())

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCliInputs)
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
