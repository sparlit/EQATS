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

from nseta.resources.resources import *


class TestResources(unittest.TestCase):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_default_config(self):
        r = resources()
        self.assertTrue(r is not None)

    def test_config_section(self):
        r = resources()
        result = r.config_section("SCANNER")
        self.assertTrue(result["UserStocksFilePath"] is not None)

    def test_invalid_config_section(self):
        r = resources()
        result = r.config_section("NON_EXISTING")
        self.assertEqual(result, None)

    def test_config_valueforkey(self):
        r = resources()
        result = r.config_valueforkey("DEFAULT", "DefaultStocksFilePath")
        self.assertEqual(result, "stocks.txt")

    def test_invalid_config_valueforkey(self):
        r = resources()
        result = r.config_valueforkey("NON_EXISTING", "NON_EXISTING_KEY")
        self.assertEqual(result, None)
        result = r.config_valueforkey("DEFAULT", "NON_EXISTING_KEY")
        self.assertEqual(result, None)

    def test_default_stocks(self):
        result = resources.default().stocks
        self.assertTrue(len(result) > 0)

    def test_rsi_config(self):
        self.assertEqual(resources.rsi().lower, int(resources().config_valueforkey("RSI", "Lower")))
        self.assertEqual(resources.rsi().upper, int(resources().config_valueforkey("RSI", "Upper")))

    def test_forecast_config(self):
        self.assertEqual(
            resources.forecast().lower, float(resources().config_valueforkey("FORECAST", "Lower"))
        )
        self.assertEqual(
            resources.forecast().upper, float(resources().config_valueforkey("FORECAST", "Upper"))
        )
        self.assertEqual(
            resources.forecast().training_percent,
            float(resources().config_valueforkey("FORECAST", "Training_percent")),
        )
        self.assertEqual(
            resources.forecast().test_percent,
            float(resources().config_valueforkey("FORECAST", "Test_percent")),
        )

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestResources)
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
