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
from nseta.analytics.model import *
from nseta.archives.archiver import archiver

FIXTURE_PATH = "tests/fixtures/BANDHANBNK_01-01-2020_08-01-2021"


class TestAnalyticsModel(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()
        archiver()
        self.df = archiver.restore_from_path(FIXTURE_PATH)

    def test_get_candle_funcs(self):
        candle_names = get_candle_funcs()
        self.assertEqual(len(candle_names), 56)

    def test_create_pattern_data(self):
        df = create_pattern_data(self.df)
        self.assertEqual(len(df.keys()), 73)
        self.assertIn("CDL3LINESTRIKE", df.columns, str(df.columns))

    def test_pick_best_rank_from_pattern(self):
        df = create_pattern_data(self.df)
        df_ranked = pick_best_rank_from_pattern(df)
        self.assertIn("candlestick_pattern", df_ranked.columns, str(df_ranked.columns))
        self.assertIn("candlestick_match_count", df_ranked.columns, str(df_ranked.columns))
        CDLENGULFING_Bull = df_ranked["candlestick_pattern"].iloc[2]
        self.assertEqual(CDLENGULFING_Bull, "CDLENGULFING_Bull")

    def test_recognize_candlestick_pattern(self):
        df_pattern = recognize_candlestick_pattern(self.df, False)
        self.assertEqual(len(df_pattern.keys()), 17)
        self.assertIn("candlestick_pattern", df_pattern.columns, str(df_pattern.columns))
        self.assertIn("candlestick_match_count", df_pattern.columns, str(df_pattern.columns))
        NO_PATTERN = df_pattern["candlestick_pattern"].iloc[0]
        self.assertEqual(NO_PATTERN, "NO_PATTERN")
        self.assertNotIn("CDLSTICKSANDWICH", df_pattern.columns, str(df_pattern.columns))
        df_pattern_steps = recognize_candlestick_pattern(self.df, True)
        self.assertIn("CDLSTICKSANDWICH", df_pattern_steps.columns, str(df_pattern_steps.columns))
        self.assertEqual(len(df_pattern_steps.keys()), 73)

    def test_model_candlestick(self):
        df_pattern = model_candlestick(self.df, steps=False, beautify=False)
        self.assertEqual(len(df_pattern.keys()), 17)
        self.assertIn("candlestick_pattern", df_pattern.columns, str(df_pattern.columns))
        self.assertIn("candlestick_match_count", df_pattern.columns, str(df_pattern.columns))
        NO_PATTERN = df_pattern["candlestick_pattern"].iloc[0]
        self.assertEqual(NO_PATTERN, "NO_PATTERN")
        self.assertNotIn("CDLSTICKSANDWICH", df_pattern.columns, str(df_pattern.columns))
        df_pattern_steps = model_candlestick(self.df, steps=True, beautify=False)
        self.assertIn("CDLSTICKSANDWICH", df_pattern_steps.columns, str(df_pattern_steps.columns))
        self.assertEqual(len(df_pattern_steps.keys()), 73)

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAnalyticsModel)
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
