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


import unittest

import pandas as pd
from cryptoalgotrading.finance import bollinger_bands
from numpy import nan
from pandas.util.testing import assert_frame_equal


class TestFinance(unittest.TestCase):
    def test_bollinger_bands(self):

        a = [10, 12, 12, 13, 9, 12, 12, 13]
        q = pd.DataFrame(a)

        res = (
            pd.DataFrame([nan, nan, nan, nan, 16.129503, 16.149725, 16.149725, 16.729503]),
            pd.DataFrame([nan, nan, nan, nan, 6.270497, 7.050275, 7.050275, 6.870497]),
            pd.DataFrame([nan, nan, nan, nan, 11.2, 11.6, 11.6, 11.8]),
        )

        assert_frame_equal(bollinger_bands(q, 5, 3)[0], res[0])
        assert_frame_equal(bollinger_bands(q, 5, 3)[1], res[1])
        assert_frame_equal(bollinger_bands(q, 5, 3)[2], res[2])
