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
from datetime import datetime

from baseUnitTest import baseUnitTest
from nseta.common.tradingtime import *


class TestTradingTime(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_ist_time(self):
        t = IST_time()
        self.assertTrue(datetime.now(), t)

    def test_ist_date(self):
        t = IST_date()
        self.assertTrue(datetime.now(), t)

    def test_is_trading_day(self):
        t = IST_datetime()
        self.assertEqual(t.weekday() <= 4, is_trading_day())

    def test_is_datetime_between(self):
        t = IST_datetime()
        b = datetime(t.year, t.month, t.day, 23, 58).time()
        e = datetime(t.year, t.month, t.day, 0, 5).time()
        c = datetime(t.year, t.month, t.day, 0, 3).time()
        self.assertTrue(is_datetime_between(b, e, c))

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTradingTime)
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
