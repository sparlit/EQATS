import datetime
import unittest

import numpy as np
import pandas as pd
import pytz
from baseUnitTest import baseUnitTest
from nseta.strategy.bollingerbandsBottomWStrategy import (
    bollingerbandsBottomWStrategy,
    is_ist_market_session_active,
    round_to_ist_tick,
)


class TestBollingerBandsBottomWStrategy(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp(redirect_logs=redirect_logs)

    def test_ist_market_session_and_tick_helpers(self):
        now_dt = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        active = is_ist_market_session_active(now_dt)
        self.assertIsInstance(active, bool)
        self.assertEqual(round_to_ist_tick(100.03), 100.05)
        self.assertEqual(round_to_ist_tick(-5.0), 0.0)

    def test_bollinger_bands_calculation(self):
        np.random.seed(42)
        dates = pd.date_range(start="2023-01-01", periods=50)
        close_prices = 100.0 + np.cumsum(np.random.randn(50))
        df = pd.DataFrame({"Date": dates, "Symbol": "TEST", "close": close_prices})

        strategy = bollingerbandsBottomWStrategy()
        bands = strategy.bollinger_bands(df)

        self.assertIn("std", bands.columns)
        self.assertIn("mid_band", bands.columns)
        self.assertIn("upper_band", bands.columns)
        self.assertIn("lower_band", bands.columns)
        self.assertEqual(len(bands), 31)

    def test_signal_generation_no_error(self):
        np.random.seed(42)
        dates = pd.date_range(start="2023-01-01", periods=100)
        close_prices = 100.0 + np.cumsum(np.random.randn(100))
        df = pd.DataFrame({"Date": dates, "Symbol": "TEST", "close": close_prices})

        strategy = bollingerbandsBottomWStrategy()
        signals = strategy.signal_generation(df)

        self.assertIn("bb_signal", signals.columns)
        self.assertIn("bb_position", signals.columns)
        self.assertIn("coordinates", signals.columns)

    def test_calculate_roi_insufficient_signals(self):
        dates = pd.date_range(start="2023-01-01", periods=5)
        df = pd.DataFrame(
            {
                "Date": dates,
                "close": [100.0, 101.0, 102.0, 103.0, 104.0],
                "bb_signal": [0, 0, 0, 0, 0],
                "bb_position": [0, 0, 0, 0, 0],
            }
        )
        strategy = bollingerbandsBottomWStrategy()
        result = strategy.calculate_roi(df, "TEST")
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
