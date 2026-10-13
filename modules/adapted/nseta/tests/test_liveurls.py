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
from datetime import datetime, timedelta

import nseta.common.urls as urls
import six
import timeout_decorator
from baseUnitTest import baseUnitTest
from nseta.live.liveurls import (
    futures_chain_url,
    holiday_list_url,
)

LOCAL_TIMEOUT = 60


class TestLiveUrls(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()
        proxy_on = False
        if proxy_on:
            urls.session.proxies.update({"http": "proxy1.wipro.com:8080"})

    def runTest(self):
        for key in TestUrls.__dict__:
            if key.find("test") == 0:
                TestUrls.__dict__[key](self)

    # def test_quote_eq_url(self):
    #   resp = quote_eq_url('SBIN', 'EQ')
    #   html_soup = BeautifulSoup(resp.text, 'lxml')
    #   hresponseDiv = html_soup.find('div', {'id': 'responseDiv'})
    #   d = json.loads(hresponseDiv.get_text())
    #   self.assertEqual(d['data'][0]['symbol'], 'SBIN')

    # def test_quote_derivative_url(self):
    #   base_expiry_date = datetime(2021,6,24)
    #   expiry_date = self.get_next_expiry_date(base_expiry_date).strftime('%d%b%Y').upper()
    #   resp = quote_derivative_url('NIFTY', 'FUTIDX', expiry_date, '-', '-')
    #   html_soup = BeautifulSoup(resp.text, 'lxml')
    #   hresponseDiv = html_soup.find('div', {'id': 'responseDiv'})
    #   d = json.loads(hresponseDiv.get_text().strip())
    #   self.assertEqual(d['data'][0]['underlying'], 'NIFTY')

    # @timeout_decorator.timeout(LOCAL_TIMEOUT)
    # def test_option_chain_url(self):
    #     '''
    #         1. Underlying symbol
    #         2. instrument (FUTSTK, OPTSTK, FUTIDX, OPTIDX)
    #         3. expiry date (ddMMMyyyy) where dd is not padded with zero when date is single digit
    #     '''

    #     resp = option_chain_url('SBIN', 'OPTSTK', '30JAN2020')
    #     self.assertGreaterEqual(resp.text.find('Open Interest'), 0)

    @timeout_decorator.timeout(LOCAL_TIMEOUT)
    def test_futures_chain_url(self):
        """
        1. Underlying symbol
        """

        resp = futures_chain_url("NIFTY")
        self.assertGreaterEqual(resp.text.find("Expiry Date"), 0)

    def test_holiday_list_url(self):
        n = datetime.now()
        resp = holiday_list_url(f"01Jan{n.year}", f"30Mar{n.year}")
        self.assertGreaterEqual(resp.text.find("Republic Day"), 0)

    def tearDown(self):
        super().tearDown()

    def get_next_expiry_date(self, base_expiry_date):
        new_expiry_date = base_expiry_date
        if base_expiry_date < datetime.now():
            new_expiry_date = self.get_next_expiry_date(base_expiry_date + timedelta(28))
        return new_expiry_date


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestLiveUrls)
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
