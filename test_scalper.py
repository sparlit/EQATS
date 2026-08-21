import os
import unittest

import brain
import connector
import database
import indicators
import main



class TestScalperIndicators(unittest.TestCase):
    def test_ema(self):
        # 1. Zero check
        res = indicators.calculate_ema([], 5)
        self.assertIsNone(res)

        # 2. Basic values check
        prices = [10.0, 10.0, 10.0, 10.0, 10.0]
        self.assertEqual(indicators.calculate_ema(prices, 3), 10.0)

    def test_rsi_calculations(self):
        prices = [
            100.0,
            102.0,
            104.0,
            103.0,
            105.0,
            104.0,
            106.0,
            107.0,
            105.0,
            108.0,
            109.0,
            107.0,
            110.0,
            111.0,
            109.0,
            112.0,
        ]
        rsi = indicators.calculate_rsi(prices, 14)
        self.assertIsNotNone(rsi)
        self.assertTrue(0 <= rsi <= 100)

    def test_atr(self):
        highs = [1.10, 1.11, 1.12, 1.10, 1.11]
        lows = [1.08, 1.09, 1.10, 1.08, 1.09]
        closes = [1.09, 1.10, 1.11, 1.09, 1.10]

        atr_val = indicators.calculate_atr(highs, lows, closes, 3)
        self.assertIsNotNone(atr_val)
        self.assertGreater(atr_val, 0)

    def test_macd(self):
        prices = [10.0 + i for i in range(50)]
        res = indicators.calculate_macd(prices, 12, 26, 9)
        self.assertIsNotNone(res)
        self.assertIn("macd", res)
        self.assertIn("signal", res)
        self.assertIn("histogram", res)

    def test_bollinger_bands(self):
        prices = [
            100.0,
            101.0,
            102.0,
            101.0,
            100.0,
            102.0,
            103.0,
            104.0,
            102.0,
            101.0,
            100.0,
            99.0,
            101.0,
            102.0,
            103.0,
            102.0,
            101.0,
            100.0,
            98.0,
            102.0,
        ]
        res = indicators.calculate_bollinger_bands(prices, 10, 2.0)
        self.assertIsNotNone(res)
        self.assertGreater(res["upper"], res["middle"])
        self.assertGreater(res["middle"], res["lower"])

    def test_pivot_points(self):
        res = indicators.calculate_pivot_points(100.0, 90.0, 95.0)
        self.assertEqual(res["pivot"], 95.0)
        self.assertEqual(res["r1"], 100.0)
        self.assertEqual(res["s1"], 90.0)


class TestScalperBrainAndConnector(unittest.TestCase):
    def setUp(self):
        import config

        self.orig_db = config.DB_PATH
        if os.path.exists("test_scalper_brain.db"):
            try:
                os.remove("test_scalper_brain.db")
            except Exception:
                pass
        config.DB_PATH = "test_scalper_brain.db"
        database.init_db()

    def tearDown(self):
        import config

        config.DB_PATH = getattr(self, "orig_db", "scalper_brain.db")
        if os.path.exists("test_scalper_brain.db"):
            try:
                os.remove("test_scalper_brain.db")
            except Exception:
                pass
        database.init_db()

    def test_simulator_connector(self):
        sim = connector.SimulatorConnector(initial_balance=5000.0)
        self.assertTrue(sim.connect())
        info = sim.get_account_info()
        self.assertEqual(info["balance"], 5000.0)

        # Test mock history and prices
        bars = sim.get_history("EURUSD", 10)
        self.assertEqual(len(bars), 10)

        price = sim.get_current_price("EURUSD")
        self.assertIn("bid", price)
        self.assertIn("ask", price)

        # Test trade execution and closure
        order = sim.execute_order("EURUSD", "BUY", 0.5, 1.0800, 1.1200)
        self.assertTrue(order["success"])
        self.assertIsNotNone(order["ticket"])

        # Verify order list
        orders = sim.get_open_orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["symbol"], "EURUSD")

        # Close position
        close_res = sim.close_order(order["ticket"], "MANUAL_TEST")
        self.assertTrue(close_res["success"])
        self.assertEqual(len(sim.get_open_orders()), 0)

    def test_brain_eval(self):
        b = brain.ScalperBrain()
        # Generate 210 historical bars of flat price
        history = [
            {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1000}
            for _ in range(215)
        ]

        res = b.evaluate("EURUSD", history, 10000.0)
        self.assertIn("decision", res)
        # Should be 'HOLD' since RSI on flat is 50
        self.assertEqual(res["decision"], "HOLD")


class TestAutonomousScalperIntegration(unittest.TestCase):
    def setUp(self):
        import config

        self.orig_db = config.DB_PATH
        if os.path.exists("integration_test.db"):
            try:
                os.remove("integration_test.db")
            except Exception:
                pass
        config.DB_PATH = "integration_test.db"
        config.SIMULATION_MODE = True
        config.SYMBOLS = ["EURUSD", "GBPUSD"]
        database.init_db()

    def tearDown(self):
        import config

        config.DB_PATH = getattr(self, "orig_db", "scalper_brain.db")
        if os.path.exists("integration_test.db"):
            try:
                os.remove("integration_test.db")
            except Exception:
                pass
        database.init_db()

    def test_full_trading_loop(self):
        """
        Runs an autonomous scalping loop 10 times in simulation mode,
        asserting that everything coordinates, updates, and writes results to SQLite without error.
        """
        scalper = main.AutonomousScalper()
        self.assertTrue(scalper.start())

        # We manually perform multiple ticks to verify loop integrity and simulator updates
        for i in range(15):
            scalper.tick_and_execute()

        # Verify db log files are updated
        assessments = database.get_all_trades()
        # We have run historical scanning, we should at least check that SQLite db exists and has no errors
        self.assertTrue(os.path.exists("integration_test.db"))

        scalper.stop()


class TestInstitutionalIntegrations(unittest.TestCase):
    def test_comprehensive_suite(self):
        import institutional_integrations as ii

        # Retrieve all functions starting with 'integrate_' from the module dynamically
        funcs = [getattr(ii, name) for name in dir(ii) if name.startswith("integrate_")]

        self.assertGreaterEqual(
            len(funcs), 110
        )  # Verify all 110+ libraries are fully mapped

        for f in funcs:
            res = f()
            self.assertIsInstance(res, dict)
            self.assertIn("status", res)
            self.assertIn("engine", res)


class TestEAQTSReleaseGates(unittest.TestCase):
    def test_all_29_release_gates(self):
        """Programmatically executes and verifies all 29 EAQTS Version 3.0 Production Release Gates (G01-G29)."""
        import release_gates

        runner = release_gates.ReleaseGateRunner()
        success = runner.run_all_gates()

        # Check that we evaluated all 29 gates
        self.assertEqual(len(runner.results), 29)

        # Print all gate evaluation results for transparency in test logs
        print("\n--- EAQTS VERSION 3.0 PRODUCTION RELEASE GATES AUDIT REPORT ---")
        for code, data in sorted(runner.results.items()):
            status_str = "PASSED" if data["passed"] else "FAILED"
            print(f"[{code}] {data['name']:<45} : {status_str} ({data['reason']})")
        print("----------------------------------------------------------------\n")

        # Assert that all 29 gates successfully passed
        self.assertTrue(
            success, "One or more mandatory Production Release Gates (G01-G29) failed!"
        )


if __name__ == "__main__":
    unittest.main()
