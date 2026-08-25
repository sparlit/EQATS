import os
import unittest

import brain
import config
import database
import main


class TestAllStrategiesAndRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_db = config.DB_PATH
        config.DB_PATH = "test_all_strategies_rules.db"
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls.orig_db
        if os.path.exists("test_all_strategies_rules.db"):
            try:
                os.remove("test_all_strategies_rules.db")
            except Exception:
                pass

    def setUp(self):
        database.init_db()
        self.brain = brain.ScalperBrain()

    def _generate_bars(self, count=220, base_price=1.1000, trend="UP"):
        bars = []
        price = base_price
        for i in range(count):
            if trend == "UP":
                price += 0.0002
            elif trend == "DOWN":
                price -= 0.0002
            elif trend == "RANGING":
                price += 0.0002 if i % 2 == 0 else -0.0002

            open_p = price - 0.0001
            high_p = price + 0.0003
            low_p = price - 0.0003
            close_p = price
            bars.append({"open": open_p, "high": high_p, "low": low_p, "close": close_p})
        return bars

    def test_01_trend_following_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "TREND_FOLLOWING"
            bars_up = self._generate_bars(220, trend="UP")
            res_up = self.brain.evaluate("EURUSD", bars_up, 10000.0)
            self.assertIn(res_up["decision"], ["BUY", "HOLD"])

            bars_down = self._generate_bars(220, trend="DOWN")
            res_down = self.brain.evaluate("EURUSD", bars_down, 10000.0)
            self.assertIn(res_down["decision"], ["SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_02_mean_reversion_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "MEAN_REVERSION"
            bars = self._generate_bars(220, trend="RANGING")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_03_macd_momentum_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "MACD_MOMENTUM"
            bars_up = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars_up, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_04_breakout_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "BREAKOUT"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_05_carry_trade_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "CARRY_TRADE"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("USDJPY", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_06_grid_trade_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "GRID_TRADE"
            bars = self._generate_bars(220, trend="RANGING")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_07_stat_arb_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "STAT_ARB"
            bars = self._generate_bars(220, trend="RANGING")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_08_orb_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "ORB"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_09_vsa_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "VSA"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_10_mtf_confluence_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "MTF_CONFLUENCE"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_11_smc_ict_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "SMC_ICT"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_12_order_flow_strategy(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "ORDER_FLOW"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_13_voting_ensemble_consensus(self):
        orig_strat = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        try:
            config.ACTIVE_STRATEGY = "VOTING_ENSEMBLE"
            bars = self._generate_bars(220, trend="UP")
            res = self.brain.evaluate("EURUSD", bars, 10000.0)
            self.assertIn(res["decision"], ["BUY", "SELL", "HOLD"])
        finally:
            config.ACTIVE_STRATEGY = orig_strat

    def test_14_asset_class_position_sizing(self):
        orig_fixed = getattr(config, "FIXED_LOT_SIZE_ONLY", True)
        try:
            config.FIXED_LOT_SIZE_ONLY = False
            # Forex Major
            lot_fx = self.brain._calculate_lot_size("EURUSD", 10000.0, 0.0020, 1.1000)
            self.assertGreater(lot_fx, 0.0)

            # JPY Pair
            lot_jpy = self.brain._calculate_lot_size("USDJPY", 10000.0, 0.20, 155.00)
            self.assertGreater(lot_jpy, 0.0)

            # Gold/Metals
            lot_gold = self.brain._calculate_lot_size("XAUUSD", 10000.0, 5.0, 2400.00)
            self.assertGreater(lot_gold, 0.0)

            # Crypto
            lot_btc = self.brain._calculate_lot_size("BTCUSD", 10000.0, 500.0, 65000.00)
            self.assertGreater(lot_btc, 0.0)

            # Indices
            lot_us30 = self.brain._calculate_lot_size("US30", 10000.0, 50.0, 39000.00)
            self.assertGreater(lot_us30, 0.0)
        finally:
            config.FIXED_LOT_SIZE_ONLY = orig_fixed

    def test_15_spread_volatility_spike_breaker(self):
        orig_bw = getattr(config, "BLOCK_WEEKENDS", True)
        orig_br = getattr(config, "BLOCK_ROLLOVER_HOUR", True)
        try:
            config.BLOCK_WEEKENDS = False
            config.BLOCK_ROLLOVER_HOUR = False
            scalper = main.AutonomousScalper()
            price_info = {"bid": 1.1000, "ask": 1.1010} # 10 pips spread
            # Populate symbol average spreads with low average (1.0 pip)
            scalper._symbol_avg_spreads = {"EURUSD": [1.0] * 10}
            is_safe, reason = scalper._is_market_open_and_liquid("EURUSD", price_info)
            self.assertFalse(is_safe)
            self.assertIn("Spread Volatility Spike Breaker", reason)
        finally:
            config.BLOCK_WEEKENDS = orig_bw
            config.BLOCK_ROLLOVER_HOUR = orig_br


if __name__ == "__main__":
    unittest.main()
