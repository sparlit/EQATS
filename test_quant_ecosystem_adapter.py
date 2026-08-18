"""
Unit test suite for Quant Ecosystem Adapters.
Validates FinGPT/FinRobot sentiment, Vibe-Trading presets, Microsoft Qlib Alpha158 features, and Backtrader bridge.
"""

import unittest
from institutional_integrations.quant_ecosystem_adapter import (
    FinRobotSentimentEngine,
    VibeHedgeFundPresets,
    QlibMLPipelineAdapter,
    BacktraderFreqtradeBridge
)

class TestQuantEcosystemAdapter(unittest.TestCase):

    def test_finrobot_sentiment_engine(self):
        engine = FinRobotSentimentEngine()

        res_bull = engine.analyze_headline("US Dollar surges on interest rate cut expectations")
        self.assertEqual(res_bull["sentiment"], "BULLISH")
        self.assertTrue(res_bull["score"] > 0)

        res_bear = engine.analyze_headline("Markets plunge amid severe recession and inflation concerns")
        self.assertEqual(res_bear["sentiment"], "BEARISH")
        self.assertTrue(res_bear["score"] < 0)

    def test_vibe_hedge_fund_presets(self):
        vibe = VibeHedgeFundPresets()
        preset = vibe.get_preset("MULTI_STRAT_MACRO")

        self.assertEqual(preset["name"], "Global Multi-Strategy Macro")
        self.assertIn("Analyst", preset["active_agents"])
        self.assertEqual(preset["max_drawdown"], 5.0)

    def test_qlib_alpha158_features(self):
        qlib = QlibMLPipelineAdapter()
        prices = [100.0 + (i * 0.5) for i in range(30)]
        highs = [p + 0.2 for p in prices]
        lows = [p - 0.2 for p in prices]

        feats = qlib.compute_alpha158_features(prices, highs, lows)
        self.assertIn("alpha158_score", feats)
        self.assertTrue(0.0 <= feats["alpha158_score"] <= 1.0)
        self.assertIn("roc_5", feats)

    def test_backtrader_freqtrade_bridge(self):
        bridge = BacktraderFreqtradeBridge()
        history = [{"close": 1.0 + (i * 0.001)} for i in range(50)]

        res = bridge.run_backtrader_simulation(history, initial_cash=10000.0)
        self.assertEqual(res["framework"], "BACKTRADER_CEREBRO_BRIDGE")
        self.assertIn("net_profit", res)
        self.assertIn("win_rate", res)

if __name__ == "__main__":
    unittest.main()
