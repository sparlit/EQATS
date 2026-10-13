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
import io
import logging
import sys
import time
import unittest

import nseta.common.urls as urls
from nseta.common.log import *


class baseUnitTest(unittest.TestCase):
    def setUp(self, redirect_logs=True):
        self.startTime = time.time()
        capturedOutput = io.StringIO()  # Create StringIO object
        sys.stdout = capturedOutput  #  and redirect stdout.
        self._capturedOutput = capturedOutput
        self._stream_handler = logging.StreamHandler(sys.stdout)
        default_logger().addHandler(self._stream_handler)
        if redirect_logs:
            logging.disable(logging.DEBUG)

    @property
    def capturedOutput(self):
        return self._capturedOutput

    @property
    def stream_handler(self):
        return self._stream_handler

    def tearDown(self):
        urls.session.close()
        default_logger().removeHandler(self.stream_handler)
        sys.stdout = sys.__stdout__  # Reset redirect.
        t = time.time() - self.startTime
        print(f"\n{self.id().ljust(100)}: {t:.3f}")
