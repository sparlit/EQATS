import ctypes
import unittest
import pandas as pd
from institutional_integrations.bayesian_consensus import BayesianConsensusEngine, global_bayesian_consensus
from institutional_integrations import aat_strategies
from institutional_integrations.aat_analyst import MacroAnalyst, SMCAnalyst, VolatilityAnalyst
from institutional_integrations.web_api import MCPServerCore

class TestAATAdaptedModules(unittest.TestCase):

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
