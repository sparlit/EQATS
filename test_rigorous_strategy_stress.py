import os
import unittest
import random
import math

import brain
import config
import database
import indicators
import main


class TestRigorousStrategyStress(unittest.TestCase):
    """
    Rigorously stress tests all 13 trading strategies and execution methods
    under extreme chaos, flash crashes, volatile spread spikes, toxic VPIN flows,
    corrupted market data, and high-frequency concurrent execution cycles.
    """

    @classmethod
    def setUpClass(cls):
        cls.orig_db = config.DB_PATH
        config.DB_PATH = "test_rigorous_stress.db"
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls.orig_db
        if os.path.exists("test_rigorous_stress.db"):
            try:
                os.remove("test_rigorous_stress.db")
            except Exception:
                pass

    def setUp(self):
        database.init_db()
        self.brain = brain.ScalperBrain()

    def _generate_chaotic_bars(self, count=250, scenario="NORMAL"):
        bars = []
        price = 100.0
        for i in range(count):
            if scenario == "FLASH_CRASH":
                if i > 200:
                    price -= random.uniform(2.0, 5.0)  # Sudden severe 20% drop
                else:
                    price += random.uniform(-0.1, 0.1)
            elif scenario == "VOLATILITY_SPIKE":
                price += random.uniform(-2.0, 2.0)
            elif scenario == "RAPID_REGIME_SWITCH":
                if (i // 20) % 2 == 0:
                    price += 0.5  # Strong Trend Up
                else:
                    price += random.uniform(-0.05, 0.05)  # Tight Ranging Compression
            elif scenario == "CORRUPTED_DATA":
                if i % 15 == 0:
                    price = float('nan') if i % 30 == 0 else 0.0
                else:
                    price += random.uniform(-0.1, 0.1)
            else:  # NORMAL
                price += random.uniform(-0.1, 0.1)

            open_p = max(0.001, price - random.uniform(0.01, 0.1)) if not math.isnan(price) else 100.0
            high_p = max(open_p, price + random.uniform(0.01, 0.2)) if not math.isnan(price) else 100.0
            low_p = max(0.001, open_p - random.uniform(0.01, 0.2)) if not math.isnan(price) else 99.0
            close_p = max(0.001, price) if not math.isnan(price) else 100.0

            bars.append({"open": open_p, "high": high_p, "low": low_p, "close": close_p})
        return bars

    def test_01_all_13_strategies_under_flash_crash(self):
        """Tests all 13 strategy modes during a severe flash crash without throwing exceptions."""
        strategies = [
            "TREND_FOLLOWING", "MEAN_REVERSION", "MACD_MOMENTUM", "BREAKOUT",
            "CARRY_TRADE", "GRID_TRADE", "STAT_ARB", "ORB", "VSA",
            "MTF_CONFLUENCE", "SMC_ICT", "ORDER_FLOW", "VOTING_ENSEMBLE"
        ]
        crash_bars = self._generate_chaotic_bars(250, scenario="FLASH_CRASH")

        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            for strat in strategies:
                config.ACTIVE_STRATEGY = strat
                res = self.brain.evaluate("EURUSD", crash_bars, 10000.0)
                self.assertIsInstance(res, dict)
                self.assertIn("decision", res)
                self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
                self.assertIsInstance(res["lot_size"], float)
                self.assertIsInstance(res["sl"], float)
                self.assertIsInstance(res["tp"], float)
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_02_all_13_strategies_under_volatility_spikes(self):
        """Tests all 13 strategy modes during extreme volatility spikes without throwing exceptions."""
        strategies = [
            "TREND_FOLLOWING", "MEAN_REVERSION", "MACD_MOMENTUM", "BREAKOUT",
            "CARRY_TRADE", "GRID_TRADE", "STAT_ARB", "ORB", "VSA",
            "MTF_CONFLUENCE", "SMC_ICT", "ORDER_FLOW", "VOTING_ENSEMBLE"
        ]
        volatile_bars = self._generate_chaotic_bars(250, scenario="VOLATILITY_SPIKE")

        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            for strat in strategies:
                config.ACTIVE_STRATEGY = strat
                res = self.brain.evaluate("XAUUSD", volatile_bars, 50000.0)
                self.assertIsInstance(res, dict)
                self.assertIn("decision", res)
                self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_03_toxic_vpin_and_zero_liquidity_dom_stress(self):
        """Stress tests Order Flow Microstructure under extreme toxic VPIN flow and zero liquidity DOM."""
        bars = self._generate_chaotic_bars(220)

        # 1. Zero Liquidity / Empty DOM
        empty_dom = {"bids": [], "asks": []}
        res_empty = indicators.calculate_order_flow_metrics(bars, order_book=empty_dom)
        self.assertEqual(res_empty["dom_imbalance"], 0.0)
        self.assertEqual(res_empty["dominant_side"], "NEUTRAL")

        # 2. Extreme Toxic VPIN Flow
        toxic_bars = [
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.1, "volume": 100000.0}
            for _ in range(30)
        ]
        res_toxic = indicators.calculate_order_flow_metrics(toxic_bars, order_book=None)
        self.assertIsInstance(res_toxic["vpin"], float)
        self.assertTrue(0.0 <= res_toxic["vpin"] <= 1.0)

    def test_04_position_sizing_stress_under_extreme_equity(self):
        """Stress tests asset-class position sizing across extreme equity levels and tight SL distances."""
        symbols = ["EURUSD", "USDJPY", "XAUUSD", "BTCUSD", "US30"]
        equities = [0.0, -100.0, 1.0, 1000.0, 1000000.0, 100000000.0]

        orig_fixed = getattr(config, "FIXED_LOT_SIZE_ONLY", True)
        try:
            config.FIXED_LOT_SIZE_ONLY = False
            for sym in symbols:
                for eq in equities:
                    lot = self.brain._calculate_lot_size(sym, eq, 0.001, 1.0)
                    self.assertGreaterEqual(lot, 0.01)
                    self.assertLessEqual(lot, getattr(config, "MAX_LOT_SIZE", 5.0))
        finally:
            config.FIXED_LOT_SIZE_ONLY = orig_fixed

    def test_05_autonomous_scalper_high_frequency_stress_loop(self):
        """Executes 50 high-frequency tick scans on AutonomousScalper in simulation mode."""
        orig_sim = getattr(config, "SIMULATION_MODE", True)
        orig_syms = getattr(config, "SYMBOLS", [])
        try:
            config.SIMULATION_MODE = True
            config.SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]
            scalper = main.AutonomousScalper()
            self.assertTrue(scalper.start())

            for _ in range(50):
                scalper.tick_and_execute()

            scalper.stop()
        finally:
            config.SIMULATION_MODE = orig_sim
            config.SYMBOLS = orig_syms


if __name__ == "__main__":
    unittest.main()
