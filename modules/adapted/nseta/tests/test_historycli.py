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

from baseUnitTest import baseUnitTest
from click.testing import CliRunner
from nseta.cli.historycli import history, pe_history


class TestHistorycli(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_history(self):
        runner = CliRunner()
        result = runner.invoke(
            history,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-01-01",
                "--end",
                "2020-01-08",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("History for symbol:BANDHANBNK", result.output, str(result.output))
        self.assertIn("Saved to: BANDHANBNK.csv", result.output, str(result.output))

    def test_pe_history(self):
        runner = CliRunner()
        result = runner.invoke(
            pe_history,
            args=["--symbol", "BANDHANBNK", "--start", "2020-01-01", "--end", "2020-01-08"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PE History for symbol:BANDHANBNK", result.output, str(result.output))
        self.assertIn("Saved to: BANDHANBNK.csv", result.output, str(result.output))

    def test_pe_history_130_days(self):
        runner = CliRunner()
        result = runner.invoke(
            pe_history,
            args=["--symbol", "BANDHANBNK", "--start", "2020-06-01", "--end", "2020-12-31"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("PE History for symbol:BANDHANBNK", result.output, str(result.output))
        self.assertIn("Saved to: BANDHANBNK.csv", result.output, str(result.output))

    def test_history_inputs(self):
        runner = CliRunner()
        result = runner.invoke(history, args=["--start", "2020-01-01", "--end", "2020-01-08"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

    def test_history_pickle(self):
        runner = CliRunner()
        result = runner.invoke(
            history,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-01-01",
                "--end",
                "2020-01-08",
                "--format",
                "pkl",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Saved to: BANDHANBNK.pkl", result.output, str(result.output))

    def test_pe_history_inputs(self):
        runner = CliRunner()
        result = runner.invoke(pe_history, args=["--start", "2020-01-01", "--end", "2020-01-08"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

    def test_pe_history_pickle(self):
        runner = CliRunner()
        result = runner.invoke(
            pe_history,
            args=[
                "--symbol",
                "BANDHANBNK",
                "--start",
                "2020-01-01",
                "--end",
                "2020-01-08",
                "--format",
                "pkl",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Saved to: BANDHANBNK.pkl", result.output, str(result.output))

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestHistorycli)
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
