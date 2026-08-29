import ctypes
import unittest
import numpy as np
import pandas as pd
from institutional_integrations.bayesian_consensus import BayesianConsensusEngine, global_bayesian_consensus
from institutional_integrations import aat_strategies
from institutional_integrations.aat_analyst import MacroAnalyst, SMCAnalyst, VolatilityAnalyst
from institutional_integrations.web_api import MCPServerCore
from institutional_integrations import itip_signal_store
from institutional_integrations.mql_colab_engine import SLTPEngine, CandlestickAIClassifier, LatencyArbitrage
from institutional_integrations.sovereign_intelligence import SovereignIntelligencePlugin
from institutional_integrations import vibe_quantlib
from institutional_integrations.openalgo_engine import OpenAlgoSmartOrderSplitter, OpenAlgoSessionSquareOffManager
from institutional_integrations.openbull_analytics import calculate_max_pain, calculate_synthetic_future_price

class TestAATAdaptedModules(unittest.TestCase):

    def test_openbull_analytics(self):
        chain = [
            {"strike": 100.0, "ce_oi": 500, "pe_oi": 100},
            {"strike": 105.0, "ce_oi": 1000, "pe_oi": 800},
            {"strike": 110.0, "ce_oi": 200, "pe_oi": 1200},
        ]
        mp = calculate_max_pain(chain)
        self.assertEqual(mp["max_pain_strike"], 105.0)

        sf = calculate_synthetic_future_price(105.0, 3.5, 2.0, 106.0)
        self.assertEqual(sf["synthetic_future_price"], 106.5)
        self.assertEqual(sf["basis"], 0.5)

    def test_openalgo_engine(self):
        splitter = OpenAlgoSmartOrderSplitter(max_slice_lot=2.0)
        slices = splitter.slice_order("EURUSD", "BUY", 5.5)
        self.assertEqual(len(slices), 3)
        self.assertEqual(slices[0]["volume"], 2.0)
        self.assertEqual(slices[1]["volume"], 2.0)
        self.assertEqual(slices[2]["volume"], 1.5)

        sq = OpenAlgoSessionSquareOffManager()
        self.assertFalse(sq.check_squareoff_required(12, 0))
        self.assertTrue(sq.check_squareoff_required(16, 55))

    def test_vibe_quantlib(self):
        # Test VPIN
        buy_v = [10.0, 15.0, 8.0, 20.0, 12.0]
        sell_v = [5.0, 8.0, 12.0, 5.0, 15.0]
        vpin_val = vibe_quantlib.calculate_vpin(buy_v, sell_v, bucket_size=10.0, n_buckets=5)
        self.assertGreaterEqual(vpin_val, 0.0)
        self.assertLessEqual(vpin_val, 1.0)

        # Test Roll spread & Kyle lambda & Amihud
        prices = [1.1000, 1.1005, 1.0998, 1.1012, 1.1008]
        roll = vibe_quantlib.calculate_roll_spread(prices)
        self.assertGreaterEqual(roll, 0.0)

        kyle = vibe_quantlib.calculate_kyle_lambda([0.0005, -0.0007, 0.0014, -0.0004], [5.0, -8.0, 12.0, -3.0])
        self.assertIsInstance(kyle, float)

        amihud = vibe_quantlib.calculate_amihud_illiquidity([0.001, 0.002, 0.0015], [10000.0, 15000.0, 12000.0])
        self.assertGreaterEqual(amihud, 0.0)

        # Test Copula
        u = [0.1, 0.3, 0.5, 0.7, 0.9]
        v = [0.2, 0.4, 0.6, 0.8, 0.95]
        cop = vibe_quantlib.calculate_copula_dependence(u, v, "clayton")
        self.assertEqual(cop["family"], "clayton")
        self.assertIn("lambda_lower", cop)

        # Test HRP
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        hrp = vibe_quantlib.calculate_hrp_weights(cov)
        self.assertEqual(len(hrp), 2)
        self.assertAlmostEqual(float(np.sum(hrp)), 1.0)

    def test_sovereign_intelligence(self):
        sov = SovereignIntelligencePlugin(max_equity_risk=0.01)
        df = pd.DataFrame([
            {"open": 1.1000 + i*0.0005, "high": 1.1010 + i*0.0005, "low": 1.0990 + i*0.0005, "close": 1.1005 + i*0.0005}
            for i in range(25)
        ])
        res = sov.analyze_market_signal("EURUSD", df, equity=10000.0)
        self.assertEqual(res["symbol"], "EURUSD")
        self.assertIn("recommended_lot", res)

    def test_mql_colab_engine(self):
        sltp = SLTPEngine()
        res = sltp.calculate_sl_tp("EURUSD", "BUY", 1.1000, 0.0015)
        self.assertLess(res["sl"], 1.1000)
        self.assertGreater(res["tp"], 1.1000)

        classifier = CandlestickAIClassifier()
        bars = [
            {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.0995},
            {"open": 1.0990, "high": 1.1025, "low": 1.0985, "close": 1.1020},
        ]
        patterns = classifier.classify_bars(bars)
        self.assertIsInstance(patterns, list)

        lat = LatencyArbitrage()
        lat.record_tick("EURUSD", "LP1", 1.1005, 1000.0)
        lat.record_tick("EURUSD", "LP2", 1.1001, 1000.0)
        lead = lat.detect_lead_lag("EURUSD", "LP1", "LP2")
        self.assertIn("lead_lag", lead)

    def test_itip_signal_store(self):
        itip_signal_store.init_store()
        sig = {
            "timestamp": "2026-08-29 00:00:00",
            "symbol": "EURUSD",
            "timeframe": "M15",
            "direction": "BUY",
            "confidence": 88.5,
            "session": "LONDON",
            "atr": 0.0012,
            "rsi": 55.0,
        }
        rec = itip_signal_store.append_signal(sig)
        self.assertEqual(rec["symbol"], "EURUSD")
        signals = itip_signal_store.read_signals()
        self.assertIsInstance(signals, list)

    def test_bayesian_consensus_engine(self):
        engine = BayesianConsensusEngine()
        engine.set_strategy_reliability("SUPER_STRAT", 0.90)

        # Test default prior
        res0 = engine.get_consensus_decision("EURUSD")
        self.assertEqual(res0["decision"], "HOLD")
        self.assertAlmostEqual(res0["posterior_probability"], 0.5)

        # Update evidence with strong BUY
        post1 = engine.update_evidence("EURUSD", "SUPER_STRAT", "BUY", raw_prob=0.85)
        self.assertGreater(post1, 0.5)

        post2 = engine.update_evidence("EURUSD", "SUPER_STRAT", "BUY", raw_prob=0.90)
        self.assertGreater(post2, post1)

        res_final = engine.get_consensus_decision("EURUSD", buy_threshold=0.70)
        self.assertEqual(res_final["decision"], "BUY")

    def test_aat_strategy_brains(self):
        # Generate dummy bullish bars
        bars = []
        p = 1.1000
        for i in range(50):
            p += 0.0002
            bars.append({
                "open": p - 0.0001,
                "high": p + 0.0003,
                "low": p - 0.0003,
                "close": p,
                "time": 1700000000 + i * 3600
            })

        supertrend_sig = aat_strategies.evaluate_supertrend(bars)
        self.assertIn(supertrend_sig, ["BUY", "SELL", "HOLD"])

        donchian_sig = aat_strategies.evaluate_donchian_breakout(bars)
        self.assertIn(donchian_sig, ["BUY", "SELL", "HOLD"])

        rsi_sig = aat_strategies.evaluate_rsi_momentum(bars)
        self.assertIn(rsi_sig, ["BUY", "SELL", "HOLD"])

        wyckoff_sig = aat_strategies.evaluate_wyckoff_master(bars)
        self.assertIn(wyckoff_sig, ["BUY", "SELL", "HOLD"])

        ict_sig = aat_strategies.evaluate_ict_killzone(bars)
        self.assertIn(ict_sig, ["BUY", "SELL", "HOLD"])

    def test_aat_analyst_subsystem(self):
        macro = MacroAnalyst()
        macro.update_sentiment(0.80)
        weight = macro.get_impact_weight("EURUSD")
        self.assertEqual(weight, 1.15)

        # SMC Analyst
        smc = SMCAnalyst()
        df = pd.DataFrame([
            {"high": 1.10 + i*0.001, "low": 1.09 + i*0.001, "close": 1.095 + i*0.001}
            for i in range(20)
        ])
        struct = smc.detect_market_structure(df)
        self.assertIn("trend", struct)

        fvgs = smc.detect_fvg(df)
        self.assertIsInstance(fvgs, list)

        # Volatility Analyst
        vol = VolatilityAnalyst()
        regime = vol.get_regime(df)
        self.assertIn(regime, ["NORMAL", "TRENDING_FAST", "TRENDING_SLOW", "RANGING_TIGHT", "HIGH_VOLATILITY", "CRASH_SUDDEN", "SPIKE_SUDDEN"])

    def test_mcp_server_core(self):
        mcp = MCPServerCore()
        status = mcp.get_system_status()
        self.assertEqual(status["status"], "ONLINE")
        self.assertEqual(status["mcp_version"], "1.0")

        exec_res = mcp.execute_trade_command("EURUSD", "BUY", 0.05)
        self.assertTrue(exec_res["success"])
        self.assertEqual(exec_res["volume"], 0.05)

        intel = mcp.query_market_intel("EURUSD")
        self.assertEqual(intel["symbol"], "EURUSD")

if __name__ == "__main__":
    unittest.main()
