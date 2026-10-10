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
import datetime
import unittest

import six
from baseUnitTest import baseUnitTest
from nseta.live.live import get_holidays_list, get_quote, getworkingdays


class TestLive(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def runTest(self):
        for key in TestUrls.__dict__:
            if key.find("test") == 0:
                TestUrls.__dict__[key](self)

    def test_get_quote_eq(self):
        q = get_quote(symbol="SBIN")
        comp_name = q["data"][0]["companyName"]
        self.assertEqual(comp_name, "State Bank of India")

    # def test_get_futures_chain(self):
    #   """
    #   1. Underlying security (stock symbol or index name)
    #   """
    #   n = datetime.datetime.now()
    #   dftable = get_futures_chain_table('NIFTY')

    #   # Atleast 3 expiry sets should be open
    #   self.assertGreaterEqual(len(dftable), 3)

    #   (dtnear, dtnext, dtfar) = dftable.index.tolist()
    #   # self.assertLess(dtnear, dtnext)
    #   # self.assertLess(dtnext, dtfar)

    def test_get_holiday_list(self):
        """
        Check holiday list for first quarter for 2019 against the expected data
        -----------------------------------------------------------
        Date               Day Of the Week             Description
        ------------------------------------------------------------
        2019-03-04          Monday           Mahashivratri
        2019-03-21        Thursday                    Holi
        """
        fromdate = datetime.date(2019, 1, 1)
        todate = datetime.date(2019, 3, 31)
        lstholiday = get_holidays_list(fromdate, todate)
        self.assertEqual(len(lstholiday), 2)
        self.assertFalse(lstholiday[lstholiday["Description"] == "Mahashivratri"].empty)
        self.assertFalse(lstholiday[lstholiday["Day"] == "Thursday"].empty)

        with self.assertRaises(ValueError):
            get_holidays_list(todate, fromdate)

    def test_working_day(self):
        # 20 to 28th aug
        independenceday = datetime.date(2021, 8, 15)
        workingdays = getworkingdays(datetime.date(2021, 8, 13), datetime.date(2021, 8, 17))
        self.assertFalse(independenceday in workingdays)
        self.assertEqual(len(workingdays), 3)

        # working days in March 2019
        # 31 day month with 2 holidays
        workingdays = getworkingdays(datetime.date(2021, 3, 1), datetime.date(2021, 3, 31))
        self.assertEqual(len(workingdays), 23)

        # working day for special dates on weekend
        workingdays = getworkingdays(datetime.date(2020, 1, 31), datetime.date(2020, 2, 3))
        self.assertEqual(len(workingdays), 3)

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestLive)
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
