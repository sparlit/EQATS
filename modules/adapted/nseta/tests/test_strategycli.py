import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from baseUnitTest import baseUnitTest
from click.testing import CliRunner
from nseta.cli.strategycli import scan_trading_strategy, test_trading_strategy
from nseta.resources.resources import *


class TestStrategycli(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_test_trading_strategy_inputs(self):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy, args=["--start", "2020-08-01", "--end", "2021-01-01"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Please provide security", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_historical_bbands(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK,BANKBARODA",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "bbands",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_historical_More_than_3_codes(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK,BANKBARODA,HDFC,ABB",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_intraday_bbands(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=["--symbol", "BANDHANBNK,BANKBARODA", "--intraday", "--strategy", "bbands"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_intraday_macd(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=["--symbol", "BANDHANBNK,BANKBARODA", "--intraday", "--strategy", "macd"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_intraday_rsi(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=["--symbol", "BANDHANBNK,BANKBARODA", "--intraday", "--strategy", "rsi"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_historical_rsi(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK,BANKBARODA",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "rsi",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_scan_trading_strategy_historical_macd(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            scan_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK,BANKBARODA",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "macd",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_bbands(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "bbands",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_rsi(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "rsi",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_macd(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "macd",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_smac(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "smac",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        # self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_emac(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "emac",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        # self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_multi(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "multi",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        # self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_historical_custom(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-08-01",
                "--end",
                "2021-01-01",
                "--strategy",
                "custom",
                "-l",
                str(resources.forecast().lower),
                "-u",
                str(resources.forecast().upper),
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        # self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_intraday(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=["--symbol", "PNB", "--strategy", "bbands", "--clear", "--intraday"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_intraday_signals_rsi(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy, args=["--symbol", "PNB", "--strategy", "rsi", "--intraday"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_intraday_signals_bbands(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy,
            args=["--symbol", "PNB", "--strategy", "bbands", "--clear", "--intraday"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    @patch("matplotlib.pyplot.show")
    def test_test_trading_strategy_intraday_signals_macd(self, mock_pyplot):
        runner = CliRunner()
        result = runner.invoke(
            test_trading_strategy, args=["--symbol", "PNB", "--strategy", "macd", "--intraday"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PnL", result.output, str(result.output))

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestStrategycli)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if six.PY2:
        if result.wasSuccessful():
            print("tests OK")
        for test, error in result.errors:
            print(f"=========Error in: {test}===========")
            print(error)
            print("======================================")

        for test, failures in result.failures:
            print(f"=========Error in: {test}===========")
            print(failures)
            print("======================================")
