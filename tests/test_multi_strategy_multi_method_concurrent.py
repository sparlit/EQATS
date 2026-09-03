import os
import unittest
from typing import Any

import brain
import config
import database


class TestMultiStrategyMultiMethodConcurrent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orig_db = config.DB_PATH
        config.DB_PATH = "test_multi_strat_method.db"
        database.init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        config.DB_PATH = cls.orig_db
        if os.path.exists("test_multi_strat_method.db"):
            try:
                os.remove("test_multi_strat_method.db")
            except Exception:
                pass

    def setUp(self) -> None:
        database.init_db()
        self.scalper_brain = brain.ScalperBrain()
        self.orig_strategy = getattr(config, "ACTIVE_STRATEGY", "MULTI_STRATEGY_CONCURRENT")
        self.orig_style = getattr(config, "TRADING_STYLE", "AUTO")
        self.orig_gate = getattr(config, "ENABLE_SYMBOL_FLOATING_LOSS_GATE", True)
        self.orig_max_trades = getattr(config, "MAX_CONCURRENT_TRADES", 20)
        config.MAX_CONCURRENT_TRADES = 9999

    def tearDown(self) -> None:
        config.ACTIVE_STRATEGY = self.orig_strategy
        config.TRADING_STYLE = self.orig_style
        config.ENABLE_SYMBOL_FLOATING_LOSS_GATE = self.orig_gate
        config.MAX_CONCURRENT_TRADES = self.orig_max_trades

    def _generate_bars(self, count: Any = 220, base_price: Any = 1.1, step: Any = 0.0003) -> Any:
        bars = []
        price = base_price
        for i in range(count):
            price += step if i % 2 == 0 else step * 0.5
            high_p = price + 0.0005
            low_p = price - 0.0005
            bars.append({"open": price - 0.0001, "high": high_p, "low": low_p, "close": price})
        return bars

    def test_multi_strategy_concurrent_evaluation(self) -> None:
        config.ACTIVE_STRATEGY = "MULTI_STRATEGY_CONCURRENT"
        config.TRADING_STYLE = "SCALPING"
        config.ENABLE_SYMBOL_FLOATING_LOSS_GATE = False
        bars = self._generate_bars(220, base_price=1.1, step=0.0004)
        res = self.scalper_brain.evaluate("EURUSD", bars, 10000.0)
        self.assertIn("decisions", res)
        self.assertIsInstance(res["decisions"], list)
        self.assertGreater(len(res["decisions"]), 0)
        for dec in res["decisions"]:
            self.assertIn(dec["decision"], ["BUY", "SELL"])
            self.assertIn("strategy", dec)
            self.assertEqual(dec["method"], "SCALPING")
            self.assertGreater(dec["lot_size"], 0.0)
            self.assertNotEqual(dec["sl"], 0.0)
            self.assertNotEqual(dec["tp"], 0.0)

    def test_multi_hybrid_parallel_evaluation(self) -> None:
        config.ACTIVE_STRATEGY = "MULTI_HYBRID_PARALLEL"
        config.TRADING_STYLE = "SCALPING"
        config.ENABLE_SYMBOL_FLOATING_LOSS_GATE = False
        bars = self._generate_bars(220, base_price=1.1, step=0.0004)
        res = self.scalper_brain.evaluate("GBPUSD", bars, 10000.0)
        self.assertIn("decisions", res)
        self.assertIsInstance(res["decisions"], list)
        self.assertGreater(len(res["decisions"]), 1)
        methods_found = {dec["method"] for dec in res["decisions"]}
        self.assertTrue(len(methods_found) >= 2)

    def test_auto_strategy_and_style_resolution(self) -> None:
        config.ACTIVE_STRATEGY = "AUTO"
        config.TRADING_STYLE = "AUTO"
        config.ENABLE_SYMBOL_FLOATING_LOSS_GATE = False
        bars = self._generate_bars(220, base_price=1.1, step=0.0004)
        res = self.scalper_brain.evaluate("USDJPY", bars, 10000.0)
        self.assertIn("decision", res)
        self.assertIn("decisions", res)

    def test_database_logging_with_strategy_and_method(self) -> None:
        import time

        ticket = f"9998811_{time.time_ns()}"
        database.log_trade_open(
            ticket=ticket,
            symbol="EURUSD",
            direction="BUY",
            open_price=1.105,
            sl=1.1,
            tp=1.115,
            lot_size=0.1,
            strategy="SMC_ICT",
            method="DAY_TRADING",
        )
        open_trades = database.get_open_trades()
        matched = [t for t in open_trades if str(t["ticket"]) == ticket]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["strategy"], "SMC_ICT")
        self.assertEqual(matched[0]["method"], "DAY_TRADING")
        database.log_trade_close(ticket, 1.115, 100.0, "TP")


if __name__ == "__main__":
    unittest.main()
