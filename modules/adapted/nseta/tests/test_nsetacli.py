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

import nseta
from baseUnitTest import baseUnitTest
from click.testing import CliRunner
from nseta.cli.nsetacli import clear, nsetacli


class TestNSEtacli(baseUnitTest):
    def setUp(self, redirect_logs=False):
        super().setUp(redirect_logs=redirect_logs)

    def test_nsetacli_entry(self):
        runner = CliRunner()
        result = runner.invoke(nsetacli, args=["--debug", "--trace"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Debug mode is on", result.output, str(result.output))
        self.assertIn("Tracing mode is on", result.output, str(result.output))

    def test_nsetacli_cmd_options(self):
        runner = CliRunner()
        result = runner.invoke(nsetacli, args=[])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage: nsetacli [OPTIONS] COMMAND [ARGS]", result.output, str(result.output))

    def test_nsetacli_version(self):
        runner = CliRunner()
        result = runner.invoke(nsetacli, args=["--version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("nseta " + nseta.__version__, result.output, str(result.output))

    def test_nsetacli_clear_deepclean(self):
        runner = CliRunner()
        result = runner.invoke(clear, args=["--deepclean"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Removed all log files, contents and downloaded/saved files.",
            result.output,
            str(result.output),
        )

    def test_nsetacli_clear(self):
        runner = CliRunner()
        result = runner.invoke(clear, args=[])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Removed top-level results that were saved earlier.", result.output, str(result.output)
        )

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNSEtacli)
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
