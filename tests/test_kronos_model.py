"""
Unit & Integration Tests for Kronos Financial Time-Series Foundation Model Integration.
"""

from datetime import datetime
import os
from typing import Any
import unittest

import numpy as np
import pandas as pd

import config
import database
import predictive_brain
from brain import ScalperBrain
from connector import SimulatorConnector
from institutional_integrations.kronos_model import (
    KronosBrokerAdapter,
    KronosFinetuneConfig,
    KronosFoundationModel,
    KronosPredictor,
    KronosTokenizer,
    MAGIC_NUMBER,
    round_to_tick,
    validate_ist_market_session,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    SEBIOrderResponse,
)


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
        self.assertTrue(all((isinstance(x, int) for x in subtokens)))
        matrix = np.array([[100.0, 105.0, 98.0, 102.0, 500.0], [102.0, 104.0, 101.0, 103.0, 600.0]])
        seq_tokens = tokenizer.tokenize_kline_sequence(matrix)
        self.assertEqual(len(seq_tokens), 2)

    def test_kronos_tokenizer_from_pretrained(self) -> None:
        tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        self.assertIsInstance(tok, KronosTokenizer)
        self.assertEqual(tok.pretrained_name, "NeoQuasar/Kronos-Tokenizer-base")

    def test_kronos_foundation_model_probabilistic_forecast(self) -> None:
        model = KronosFoundationModel(model_size="mini")
        ohlcv = np.array(
            [[100.0 + i * 0.1, 101.0 + i * 0.1, 99.0 + i * 0.1, 100.5 + i * 0.1, 1000.0] for i in range(50)]
        )
        forecast = model.forecast_probabilistic(ohlcv, forecast_horizon=24, num_simulations=20, T=1.0, top_p=0.9)
        self.assertIn("upside_probability", forecast)
        self.assertIn("volatility_amplification", forecast)
        self.assertIn("mean_trajectory", forecast)
        self.assertIn("upper_bound", forecast)
        self.assertIn("lower_bound", forecast)
        self.assertIn("model_confidence", forecast)
        self.assertEqual(len(forecast["mean_trajectory"]), 24)
        self.assertGreaterEqual(forecast["upside_probability"], 0.0)
        self.assertLessEqual(forecast["upside_probability"], 1.0)

    def test_kronos_foundation_model_from_pretrained(self) -> None:
        model = KronosFoundationModel.from_pretrained("NeoQuasar/Kronos-small")
        self.assertIsInstance(model, KronosFoundationModel)
        self.assertEqual(model.model_size, "small")

    def test_kronos_predictor_predict_and_batch(self) -> None:
        model = KronosFoundationModel(model_size="mini")
        tokenizer = KronosTokenizer()
        predictor = KronosPredictor(model=model, tokenizer=tokenizer, max_context=512)

        df = pd.DataFrame(
            {
                "open": [100.0 + i for i in range(20)],
                "high": [102.0 + i for i in range(20)],
                "low": [99.0 + i for i in range(20)],
                "close": [101.0 + i for i in range(20)],
                "volume": [1000.0] * 20,
            }
        )
        x_ts = pd.date_range("2026-01-01", periods=20, freq="5min")
        y_ts = pd.date_range("2026-01-01 01:40", periods=5, freq="5min")

        res_df = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=5, T=1.0, top_p=0.9)
        self.assertIsInstance(res_df, pd.DataFrame)
        self.assertEqual(len(res_df), 5)
        self.assertIn("close", res_df.columns)

        batch_res = predictor.predict_batch([df, df], [x_ts, x_ts], [y_ts, y_ts], pred_len=5)
        self.assertEqual(len(batch_res), 2)
        self.assertIsInstance(batch_res[0], pd.DataFrame)

    def test_kronos_finetune_config(self) -> None:
        cfg = KronosFinetuneConfig(batch_size=16, epochs=5)
        self.assertEqual(cfg.batch_size, 16)
        self.assertEqual(cfg.epochs, 5)

    def test_kronos_broker_adapter_and_registry(self) -> None:
        adapter = KronosBrokerAdapter()
        self.assertTrue(adapter.connect())
        self.assertTrue(adapter.is_connected())
        self.assertEqual(adapter.magic_number, MAGIC_NUMBER)

        req = SEBIOrderRequest(
            symbol="RELIANCE",
            order_type="BUY",
            quantity=10,
            price=2450.123,
            sl=2400.0,
            tp=2500.0,
        )
        resp = adapter.execute_order(req)
        self.assertIsInstance(resp, SEBIOrderResponse)
        self.assertTrue(resp.success)
        self.assertEqual(resp.price, 2450.1)  # Rounded to 0.05 tick size

        registered_cls = IndianBrokerPluginRegistry.get_adapter_class("KRONOS_FOUNDATION_MODEL")
        self.assertEqual(registered_cls, KronosBrokerAdapter)

    def test_tick_rounding_and_ist_session(self) -> None:
        self.assertEqual(round_to_tick(100.03), 100.05)
        self.assertEqual(round_to_tick(100.02), 100.0)
        self.assertEqual(round_to_tick(-10.0), 0.0)

        dt_market = datetime(2026, 3, 2, 10, 30, 0)  # Monday 10:30 AM
        self.assertTrue(validate_ist_market_session(dt_market))

        dt_weekend = datetime(2026, 3, 1, 10, 30, 0)  # Sunday 10:30 AM
        self.assertFalse(validate_ist_market_session(dt_weekend))

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
