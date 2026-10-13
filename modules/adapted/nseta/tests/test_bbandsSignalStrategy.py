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
import logging
import unittest

from baseUnitTest import baseUnitTest
from nseta.common.log import default_logger
from nseta.strategy.bbandsSignalStrategy import bbandsSignalStrategy


class TestBbandsSignalStrategy(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_update_ledger_debug(self):
        default_logger().setLevel(logging.DEBUG)
        bbands = bbandsSignalStrategy(requires_ledger=True)
        bbands.index(100, 100, 100, "2021-01-18")
        report = bbands.report.to_string(index=False)
        self.assertIn("BBands-U", report, report)
        self.assertIn("BBands-L", report, report)

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBbandsSignalStrategy)
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
