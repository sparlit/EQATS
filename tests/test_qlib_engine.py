"""
Unit tests for Qlib Module & Institutional Engine Integration
"""

import unittest
import pandas as pd
import numpy as np

from institutional_integrations.qlib_engine import QlibEngine


class TestQlibEngine(unittest.TestCase):

    def setUp(self):
        # Generate synthetic OHLCV market data for testing
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        symbols = ["RELIANCE", "TCS", "INFY"]
        data = []
        for d in dates:
            for s in symbols:
                base_p = 100.0 if s == "RELIANCE" else (200.0 if s == "TCS" else 150.0)
                noise = np.random.uniform(-2.0, 2.0)
                close = base_p + noise
                open_p = close - np.random.uniform(-1.0, 1.0)
                high = max(open_p, close) + np.random.uniform(0.5, 2.0)
                low = min(open_p, close) - np.random.uniform(0.5, 2.0)
                vol = np.random.randint(1000, 5000)
                data.append({
                    "date": d,
                    "symbol": s,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": vol,
                })
        self.df_market = pd.DataFrame(data)

    def test_qlib_engine_initialization(self):
        engine = QlibEngine()
        self.assertTrue(engine.is_ready)

    def test_alpha_feature_extraction(self):
        engine = QlibEngine()
        df_feat = engine.generate_alpha_features(self.df_market)
        self.assertIn("KMID", df_feat.columns)
        self.assertIn("ROC_5", df_feat.columns)
        self.assertIn("MA_10", df_feat.columns)
        self.assertIn("label", df_feat.columns)
        self.assertEqual(len(df_feat), len(self.df_market))

    def test_qlib_engine_pipeline(self):
        engine = QlibEngine()
        self.assertTrue(engine.is_ready)

        # 1. Feature extraction
        df_feat = engine.generate_alpha_features(self.df_market)
        self.assertIn("KMID", df_feat.columns)

        # 2. Train Model
        feature_cols = [c for c in df_feat.columns if c not in ["date", "symbol", "label"]]
        train_res = engine.train_alpha_model(df_feat, feature_cols=feature_cols, model_type="gbdt")
        self.assertEqual(train_res["model_type"], "gbdt")
        self.assertIn("score", train_res["predictions"].columns)

        # 3. Predict Signals
        df_signals = engine.predict_signals(df_feat)
        self.assertIn("score", df_signals.columns)

        # 4. Strategy Backtest
        bt_res = engine.backtest_topk_strategy(self.df_market, df_signals, top_k=2)
        self.assertIn("total_return", bt_res)
        self.assertIn("sharpe_ratio", bt_res)
        self.assertIn("equity_curve", bt_res)


if __name__ == "__main__":
    unittest.main()
