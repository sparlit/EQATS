import os
import unittest

import brain
import connector
import database
import indicators
import main


class TestScalperIndicators(unittest.TestCase):

    def test_ema(self) -> None:
        res = indicators.calculate_ema([], 5)
        self.assertIsNone(res)
        prices = [10.0, 10.0, 10.0, 10.0, 10.0]
        self.assertEqual(indicators.calculate_ema(prices, 3), 10.0)

    def test_rsi_calculations(self) -> None:
        prices = [100.0, 102.0, 104.0, 103.0, 105.0, 104.0, 106.0, 107.0, 105.0, 108.0, 109.0, 107.0, 110.0, 111.0, 109.0, 112.0]
        rsi = indicators.calculate_rsi(prices, 14)
        self.assertIsNotNone(rsi)
        self.assertTrue(0 <= rsi <= 100)

    def test_atr(self) -> None:
        highs = [1.1, 1.11, 1.12, 1.1, 1.11]
        lows = [1.08, 1.09, 1.1, 1.08, 1.09]
        closes = [1.09, 1.1, 1.11, 1.09, 1.1]
        atr_val = indicators.calculate_atr(highs, lows, closes, 3)
        self.assertIsNotNone(atr_val)
        self.assertGreater(atr_val, 0)

    def test_macd(self) -> None:
        prices = [10.0 + i for i in range(50)]
        res = indicators.calculate_macd(prices, 12, 26, 9)
        self.assertIsNotNone(res)
        self.assertIn('macd', res)
        self.assertIn('signal', res)
        self.assertIn('histogram', res)

    def test_bollinger_bands(self) -> None:
        prices = [100.0, 101.0, 102.0, 101.0, 100.0, 102.0, 103.0, 104.0, 102.0, 101.0, 100.0, 99.0, 101.0, 102.0, 103.0, 102.0, 101.0, 100.0, 98.0, 102.0]
        res = indicators.calculate_bollinger_bands(prices, 10, 2.0)
        self.assertIsNotNone(res)
        self.assertGreater(res['upper'], res['middle'])
        self.assertGreater(res['middle'], res['lower'])

    def test_bollinger_squeeze(self) -> None:
        # 1. Insufficient or empty price series
        self.assertIsNone(indicators.calculate_bollinger_squeeze([], period=20))
        prices_short = [100.0, 101.0, 102.0]
        self.assertIsNone(indicators.calculate_bollinger_squeeze(prices_short, period=20))
        self.assertIsNone(indicators.calculate_bollinger_squeeze([100.0] * 20, period=0))

        # 2. Normal price series
        prices = [100.0, 101.0, 102.0, 101.0, 100.0, 102.0, 103.0, 104.0, 102.0, 101.0,
                  100.0, 99.0, 101.0, 102.0, 103.0, 102.0, 101.0, 100.0, 98.0, 102.0]
        squeeze = indicators.calculate_bollinger_squeeze(prices, period=10, num_std=2.0)
        self.assertIsNotNone(squeeze)
        self.assertIsInstance(squeeze, float)
        self.assertGreater(squeeze, 0.0)

        # Confirm consistency with calculate_bollinger_bands bandwidth output
        bb = indicators.calculate_bollinger_bands(prices, period=10, num_std=2.0)
        self.assertIsNotNone(bb)
        self.assertAlmostEqual(squeeze, bb['bandwidth'], places=7)

        # 3. Custom period and num_std
        squeeze_custom = indicators.calculate_bollinger_squeeze(prices, period=5, num_std=1.5)
        self.assertIsNotNone(squeeze_custom)
        self.assertIsInstance(squeeze_custom, float)

        # 4. Zero middle band edge case
        zero_prices = [0.0] * 20
        self.assertIsNone(indicators.calculate_bollinger_squeeze(zero_prices, period=10))

    def test_pivot_points(self) -> None:
        res = indicators.calculate_pivot_points(100.0, 90.0, 95.0)
        self.assertEqual(res['pivot'], 95.0)
        self.assertEqual(res['r1'], 100.0)
        self.assertEqual(res['s1'], 90.0)

    def test_ichimoku(self) -> None:
        res_empty = indicators.calculate_ichimoku([], [], [])
        self.assertEqual(res_empty, {"tenkan": 0.0, "kijun": 0.0})

        closes_short = [10.0 + i for i in range(10)]
        highs_short = [10.5 + i for i in range(10)]
        lows_short = [9.5 + i for i in range(10)]
        res_short = indicators.calculate_ichimoku(highs_short, lows_short, closes_short)
        self.assertEqual(res_short, {"tenkan": closes_short[-1], "kijun": closes_short[-1]})

        highs = [10.0 + i for i in range(30)]
        lows = [1.0 + i for i in range(30)]
        closes = [5.0 + i for i in range(30)]
        res = indicators.calculate_ichimoku(highs, lows, closes)
        self.assertIn("tenkan", res)
        self.assertIn("kijun", res)
        self.assertEqual(res["tenkan"], 30.5)
        self.assertEqual(res["kijun"], 22.0)
    def test_donchian_channels(self) -> None:
        # 1. Edge case: empty, None, insufficient data length, or invalid period (returns None)
        self.assertIsNone(indicators.calculate_donchian_channels([], []))
        self.assertIsNone(indicators.calculate_donchian_channels(None, None))
        self.assertIsNone(indicators.calculate_donchian_channels([10.0] * 5, [9.0] * 5, period=20))
        self.assertIsNone(indicators.calculate_donchian_channels([10.0] * 20, [9.0] * 5, period=20))
        self.assertIsNone(indicators.calculate_donchian_channels([10.0] * 20, [9.0] * 20, period=0))
        self.assertIsNone(indicators.calculate_donchian_channels([10.0] * 20, [9.0] * 20, period=-5))

        # 2. Standard price series with period=20 (default)
        highs = [10.0 + i for i in range(25)]
        lows = [8.0 + i for i in range(25)]
        res_std = indicators.calculate_donchian_channels(highs, lows, period=20)
        self.assertIsNotNone(res_std)
        self.assertIn("upper", res_std)
        self.assertIn("lower", res_std)
        self.assertIn("middle", res_std)
        self.assertEqual(res_std["upper"], 34.0)
        self.assertEqual(res_std["lower"], 13.0)
        self.assertEqual(res_std["middle"], 23.5)

        # 3. Custom period parameters (period=5)
        res_custom = indicators.calculate_donchian_channels(highs, lows, period=5)
        self.assertIsNotNone(res_custom)
        self.assertEqual(res_custom["upper"], 34.0)
        self.assertEqual(res_custom["lower"], 28.0)
        self.assertEqual(res_custom["middle"], 31.0)

        # 4. Flat price series
        highs_flat = [15.0] * 20
        lows_flat = [10.0] * 20
        res_flat = indicators.calculate_donchian_channels(highs_flat, lows_flat, period=20)
        self.assertIsNotNone(res_flat)
        self.assertEqual(res_flat["upper"], 15.0)
        self.assertEqual(res_flat["lower"], 10.0)
        self.assertEqual(res_flat["middle"], 12.5)

    def test_stochastic(self) -> None:
        # 1. Edge case: empty or insufficient data (< period)
        res_empty = indicators.calculate_stochastic([], [], [])
        self.assertEqual(res_empty, {"k": 50.0, "d": 50.0})

        highs_short = [10.0, 11.0, 12.0]
        lows_short = [9.0, 10.0, 11.0]
        closes_short = [9.5, 10.5, 11.5]
        res_short = indicators.calculate_stochastic(highs_short, lows_short, closes_short, period=14)
        self.assertEqual(res_short, {"k": 50.0, "d": 50.0})

        # 2. Flat price series (denom == 0)
        highs_flat = [10.0] * 20
        lows_flat = [10.0] * 20
        closes_flat = [10.0] * 20
        res_flat = indicators.calculate_stochastic(highs_flat, lows_flat, closes_flat, period=14, d_period=3)
        self.assertEqual(res_flat, {"k": 50.0, "d": 50.0})

        # 3. Standard price series with period=14, d_period=3
        highs = [10.0 + i * 0.5 for i in range(20)]
        lows = [8.0 + i * 0.5 for i in range(20)]
        closes = [9.0 + i * 0.5 for i in range(20)]
        res_std = indicators.calculate_stochastic(highs, lows, closes, period=14, d_period=3)
        self.assertIn("k", res_std)
        self.assertIn("d", res_std)
        self.assertIsInstance(res_std["k"], float)
        self.assertIsInstance(res_std["d"], float)
        self.assertTrue(0.0 <= res_std["k"] <= 100.0)
        self.assertTrue(0.0 <= res_std["d"] <= 100.0)

        # 4. Custom period parameters (period=5, d_period=2)
        res_custom = indicators.calculate_stochastic(highs, lows, closes, period=5, d_period=2)
        self.assertIn("k", res_custom)
        self.assertIn("d", res_custom)
        self.assertTrue(0.0 <= res_custom["k"] <= 100.0)
        self.assertTrue(0.0 <= res_custom["d"] <= 100.0)

    def test_adx(self) -> None:
        # 1. Edge case: empty or insufficient data (< period * 2)
        self.assertEqual(indicators.calculate_adx([], [], []), 20.0)

        highs_short = [10.0 + i for i in range(10)]
        lows_short = [9.0 + i for i in range(10)]
        closes_short = [9.5 + i for i in range(10)]
        self.assertEqual(indicators.calculate_adx(highs_short, lows_short, closes_short, period=14), 20.0)

        # 2. Flat price series (zero true range / zero movement)
        highs_flat = [10.0] * 35
        lows_flat = [10.0] * 35
        closes_flat = [10.0] * 35
        res_flat = indicators.calculate_adx(highs_flat, lows_flat, closes_flat, period=14)
        self.assertIsInstance(res_flat, float)
        self.assertTrue(0.0 <= res_flat <= 100.0)

        # 3. Standard strong trending price series
        highs_trend = [10.0 + i * 0.5 for i in range(40)]
        lows_trend = [9.0 + i * 0.5 for i in range(40)]
        closes_trend = [9.8 + i * 0.5 for i in range(40)]
        res_trend = indicators.calculate_adx(highs_trend, lows_trend, closes_trend, period=14)
        self.assertIsInstance(res_trend, float)
        self.assertTrue(0.0 <= res_trend <= 100.0)

        # 4. Custom period parameter
        highs_custom = [10.0 + i * 0.2 for i in range(15)]
        lows_custom = [9.0 + i * 0.2 for i in range(15)]
        closes_custom = [9.5 + i * 0.2 for i in range(15)]
        res_custom = indicators.calculate_adx(highs_custom, lows_custom, closes_custom, period=5)
        self.assertIsInstance(res_custom, float)
        self.assertTrue(0.0 <= res_custom <= 100.0)

class TestScalperBrainAndConnector(unittest.TestCase):

    def _reset_global_state(self) -> None:
        try:
            from institutional_integrations.bayesian_consensus import global_bayesian_consensus
            global_bayesian_consensus.symbol_state.clear()
        except Exception:
            pass
        try:
            from institutional_integrations.nofx_ai_terminal_engine import (
                global_nofx_direction_board,
            )
            global_nofx_direction_board.directions.clear()
        except Exception:
            pass
        try:
            import predictive_brain
            predictive_brain._predictor_registry.clear()
            predictive_brain._kronos_registry.clear()
        except Exception:
            pass

    def setUp(self) -> None:
        import config
        self.orig_db = config.DB_PATH
        self.orig_active_strategy = getattr(config, 'ACTIVE_STRATEGY', 'AUTO')
        self.orig_trading_style = getattr(config, 'TRADING_STYLE', 'AUTO')
        for db_file in ['test_scalper_brain.db', 'test_scalper_brain.db-wal', 'test_scalper_brain.db-shm']:
            if os.path.exists(db_file):
                try:
                    os.remove(db_file)
                except Exception:
                    pass
        config.DB_PATH = 'test_scalper_brain.db'
        config.ACTIVE_STRATEGY = 'AUTO'
        config.TRADING_STYLE = 'AUTO'
        self._reset_global_state()
        database.init_db()

    def tearDown(self) -> None:
        import config
        config.DB_PATH = getattr(self, 'orig_db', 'scalper_brain.db')
        config.ACTIVE_STRATEGY = getattr(self, 'orig_active_strategy', 'AUTO')
        config.TRADING_STYLE = getattr(self, 'orig_trading_style', 'AUTO')
        for db_file in ['test_scalper_brain.db', 'test_scalper_brain.db-wal', 'test_scalper_brain.db-shm']:
            if os.path.exists(db_file):
                try:
                    os.remove(db_file)
                except Exception:
                    pass
        self._reset_global_state()
        database.init_db()

    def test_simulator_connector(self) -> None:
        sim = connector.SimulatorConnector(initial_balance=5000.0)
        self.assertTrue(sim.connect())
        info = sim.get_account_info()
        self.assertEqual(info['balance'], 5000.0)
        bars = sim.get_history('EURUSD', 10)
        self.assertEqual(len(bars), 10)
        price = sim.get_current_price('EURUSD')
        self.assertIn('bid', price)
        self.assertIn('ask', price)
        order = sim.execute_order('EURUSD', 'BUY', 0.5, 1.08, 1.12)
        self.assertTrue(order['success'])
        self.assertIsNotNone(order['ticket'])
        orders = sim.get_open_orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['symbol'], 'EURUSD')
        close_res = sim.close_order(order['ticket'], 'MANUAL_TEST')
        self.assertTrue(close_res['success'])
        self.assertEqual(len(sim.get_open_orders()), 0)

    def test_brain_eval(self) -> None:
        b = brain.ScalperBrain()
        history = [{'open': 1.1, 'high': 1.101, 'low': 1.099, 'close': 1.1} for _ in range(215)]
        res = b.evaluate('EURUSD', history, 10000.0)
        self.assertIn('decision', res)
        self.assertEqual(res['decision'], 'HOLD')

    def test_order_flow_metrics_calculation(self) -> None:
        history = [{'open': 1.1 + i * 0.0001, 'high': 1.1005 + i * 0.0001, 'low': 1.0995 + i * 0.0001, 'close': 1.1004 + i * 0.0001} for i in range(25)]
        order_book = {'bids': [(1.102, 100.0), (1.1019, 150.0)], 'asks': [(1.1021, 20.0), (1.1022, 30.0)]}
        res = indicators.calculate_order_flow_metrics(history, order_book=order_book)
        self.assertIn('vpin', res)
        self.assertIn('dom_imbalance', res)
        self.assertGreater(res['dom_imbalance'], 0.0)
        self.assertEqual(res['dominant_side'], 'BUY_DOMINANT')

class TestAutonomousScalperIntegration(unittest.TestCase):

    def setUp(self) -> None:
        import config
        self.orig_db = config.DB_PATH
        for db_file in ['integration_test.db', 'integration_test.db-wal', 'integration_test.db-shm']:
            if os.path.exists(db_file):
                try:
                    os.remove(db_file)
                except Exception:
                    pass
        config.DB_PATH = 'integration_test.db'
        config.SIMULATION_MODE = True
        config.SYMBOLS = ['EURUSD', 'GBPUSD']
        database.init_db()

    def tearDown(self) -> None:
        import config
        config.DB_PATH = getattr(self, 'orig_db', 'scalper_brain.db')
        for db_file in ['integration_test.db', 'integration_test.db-wal', 'integration_test.db-shm']:
            if os.path.exists(db_file):
                try:
                    os.remove(db_file)
                except Exception:
                    pass
        database.init_db()

    def test_full_trading_loop(self) -> None:
        """
        Runs an autonomous scalping loop 10 times in simulation mode,
        asserting that everything coordinates, updates, and writes results to SQLite without error.
        """
        scalper = main.AutonomousScalper()
        self.assertTrue(scalper.start())
        for i in range(15):
            scalper.tick_and_execute()
        database.get_all_trades()
        self.assertTrue(os.path.exists('integration_test.db'))
        scalper.stop()

class TestInstitutionalIntegrations(unittest.TestCase):

    def test_comprehensive_suite(self) -> None:
        import institutional_integrations as ii
        funcs = [getattr(ii, name) for name in dir(ii) if name.startswith('integrate_')]
        self.assertGreaterEqual(len(funcs), 110)
        for f in funcs:
            res = f()
            self.assertIsInstance(res, dict)
            self.assertIn('status', res)
            self.assertIn('engine', res)

class TestEQATSReleaseGates(unittest.TestCase):

    def test_all_29_release_gates(self) -> None:
        """Programmatically executes and verifies all 29 EQATS Version 3.0 Production Release Gates (G01-G29)."""
        import release_gates
        runner = release_gates.ReleaseGateRunner()
        success = runner.run_all_gates()
        self.assertEqual(len(runner.results), 29)
        print('\n--- EQATS VERSION 3.0 PRODUCTION RELEASE GATES AUDIT REPORT ---')
        for code, data in sorted(runner.results.items()):
            status_str = 'PASSED' if data['passed'] else 'FAILED'
            print(f"[{code}] {data['name']:<45} : {status_str} ({data['reason']})")
        print('----------------------------------------------------------------\n')
        self.assertTrue(success, 'One or more mandatory Production Release Gates (G01-G29) failed!')
if __name__ == '__main__':
    unittest.main()
