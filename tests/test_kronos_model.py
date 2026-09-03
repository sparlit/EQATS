"""
Unit & Integration Tests for Kronos Financial Time-Series Foundation Model Integration.
"""

import os
import unittest
from typing import Any

import numpy as np

import config
import database
import predictive_brain
from brain import ScalperBrain
from connector import SimulatorConnector
from institutional_integrations.kronos_model import KronosFoundationModel, KronosTokenizer


class TestKronosModelIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.orig_db = config.DB_PATH
        if os.path.exists("test_kronos.db"):
            try:
                os.remove("test_kronos.db")
            except Exception:
                pass
        config.DB_PATH = "test_kronos.db"
        database.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = getattr(self, "orig_db", "scalper_brain.db")
        if os.path.exists("test_kronos.db"):
            try:
                os.remove("test_kronos.db")
            except Exception:
                pass
        database.init_db()

    def test_kronos_tokenizer_basic(self) -> None:
        tokenizer = KronosTokenizer(num_bins=64)
        subtokens = tokenizer.tokenize_bar(100.0, 105.0, 98.0, 102.0, 500.0, 100.0)
        self.assertEqual(len(subtokens), 4)
        self.assertTrue(all(isinstance(x, int) for x in subtokens))
        matrix = np.array([[100.0, 105.0, 98.0, 102.0, 500.0], [102.0, 104.0, 101.0, 103.0, 600.0]])
        seq_tokens = tokenizer.tokenize_kline_sequence(matrix)
        self.assertEqual(len(seq_tokens), 2)

    def test_kronos_foundation_model_probabilistic_forecast(self) -> None:
        model = KronosFoundationModel(model_size="mini")
        ohlcv = np.array(
            [[100.0 + i * 0.1, 101.0 + i * 0.1, 99.0 + i * 0.1, 100.5 + i * 0.1, 1000.0] for i in range(50)],
        )
        forecast = model.forecast_probabilistic(ohlcv, forecast_horizon=24, num_simulations=20)
        self.assertIn("upside_probability", forecast)
        self.assertIn("volatility_amplification", forecast)
        self.assertIn("mean_trajectory", forecast)
        self.assertIn("upper_bound", forecast)
        self.assertIn("lower_bound", forecast)
        self.assertIn("model_confidence", forecast)
        self.assertEqual(len(forecast["mean_trajectory"]), 24)
        self.assertGreaterEqual(forecast["upside_probability"], 0.0)
        self.assertLessEqual(forecast["upside_probability"], 1.0)

    def test_predictive_brain_kronos_factory(self) -> None:
        kronos_inst = predictive_brain.get_kronos_predictor("EURUSD")
        self.assertIsInstance(kronos_inst, KronosFoundationModel)

    def test_brain_kronos_veto_filter_integration(self) -> None:
        conn = SimulatorConnector()
        brain_inst = ScalperBrain()
        brain_inst.conn = conn
        history_bars = conn.get_history("EURUSD", 250)
        decision = brain_inst.evaluate("EURUSD", history_bars, 10000.0)
        self.assertIn("decision", decision)
        self.assertIn(decision["decision"], ["BUY", "SELL", "HOLD"])


if __name__ == "__main__":
    unittest.main()
