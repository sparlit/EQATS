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
import sys
import unittest

from baseUnitTest import baseUnitTest
from nseta.common import log
from nseta.common.log import *


class TestLog(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp(redirect_logs=False)
        logging.disable(logging.NOTSET)

    def test_debug_log(self):
        log.setup_custom_logger("nseta", logging.DEBUG, False, filter=None)
        default_logger().debug("test_debug_log")
        sys.stdout.flush()
        self.assertIn("test_debug_log", self.capturedOutput.getvalue())

    def test_debug_log_filter(self):
        log.setup_custom_logger("nseta", logging.DEBUG, False, filter="test_log.py")
        default_logger().setLevel(logging.INFO)
        self.assertEqual(default_logger().level, logging.INFO)
        default_logger().level = logging.WARN
        self.assertEqual(default_logger().level, logging.WARN)
        default_logger().setLevel(logging.DEBUG)
        default_logger().debug("test_debug_log_filter")
        self.assertIn("test_debug_log_filter", self.capturedOutput.getvalue())
        self.assertIn("test_log.py", self.capturedOutput.getvalue())

    def test_debug_log_filter_info(self):
        log.setup_custom_logger("nseta", logging.INFO, False, filter="test_debug_log_filter_info")
        default_logger().info("test_debug_log_filter_info")
        self.assertIn("test_debug_log_filter_info", self.capturedOutput.getvalue())

    def test_debug_log_filter_warn(self):
        log.setup_custom_logger("nseta", logging.WARN, False, filter="test_debug_log_filter_warn")
        default_logger().warn("test_debug_log_filter_warn")
        self.assertIn("test_debug_log_filter_warn", self.capturedOutput.getvalue())

    def test_debug_log_filter_error(self):
        log.setup_custom_logger("nseta", logging.ERROR, False, filter="test_debug_log_filter_error")
        default_logger().error("test_debug_log_filter_error")
        self.assertIn("test_debug_log_filter_error", self.capturedOutput.getvalue())

    def test_debug_log_filter_critical(self):
        log.setup_custom_logger(
            "nseta", logging.CRITICAL, False, filter="test_debug_log_filter_critical"
        )
        default_logger().critical("test_debug_log_filter_critical")
        self.assertIn("test_debug_log_filter_critical", self.capturedOutput.getvalue())

    def tearDown(self):
        log.setup_custom_logger("nseta", logging.INFO, False, filter=None)
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestLog)
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
