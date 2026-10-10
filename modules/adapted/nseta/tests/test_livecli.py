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
import threading
import time
import unittest

from baseUnitTest import baseUnitTest
from click.testing import CliRunner
from nseta.cli.livecli import live_quote, news, scan, top_picks
from nseta.scanner.scannerFactory import *
from nseta.scanner.stockscanner import *


class TestLivecli(baseUnitTest):
    def setUp(self, redirect_logs=True):
        super().setUp()

    def test_live_quote(self):
        runner = CliRunner()
        result = runner.invoke(live_quote, args=["--symbol", "BANDHANBNK", "-gowvb"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Symbol              |            BANDHANBNK", result.output, str(result.output)
        )
        self.assertIn(
            "Name                |  Bandhan Bank Limited", result.output, str(result.output)
        )
        self.assertIn(
            "ISIN                |          INE545U01014", result.output, str(result.output)
        )
        self.assertIn("Last Updated        |", result.output, str(result.output))
        self.assertIn("Prev Close", result.output, str(result.output))
        self.assertIn("Last Trade Price", result.output, str(result.output))
        self.assertIn("Change", result.output, str(result.output))
        self.assertIn("% Change", result.output, str(result.output))
        self.assertIn("Avg. Price", result.output, str(result.output))
        self.assertIn("open", result.output, str(result.output))
        self.assertIn("52 Wk High", result.output, str(result.output))
        self.assertIn("Total Traded Volume", result.output, str(result.output))
        self.assertIn("% Delivery", result.output, str(result.output))
        self.assertIn(
            "Bid Quantity        | Bid Price           | Offer_Quantity      | Offer_Price",
            result.output,
            str(result.output),
        )

    def test_scan_intraday(self):
        runner = CliRunner()
        result = runner.invoke(
            scan,
            args=["--stocks", "BANDHANBNK,HDFC", "--intraday", "--indicator", "all", "--clear"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Intraday scanning finished.", result.output, str(result.output))

    def test_scan_intraday_background(self):
        s = scannerFactory.scanner(ScannerType.Intraday, ["HDFC"], "emac", True)
        scannerinstance = scanner(indicator="rsi")
        result = s.scan_background(scannerinstance, terminate_after_iter=2, wait_time=2)
        self.assertEqual(result, 2)

    def test_scan_live(self):
        runner = CliRunner()
        result = runner.invoke(
            scan, args=["--stocks", "BANDHANBNK,HDFC", "--live", "--indicator", "all", "--clear"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Live scanning finished.", result.output, str(result.output))

    def test_scan_live_background(self):
        s = scannerFactory.scanner(ScannerType.Live, ["HDFC"], "emac", True)
        scannerinstance = scanner(indicator="rsi")
        result = s.scan_background(scannerinstance, terminate_after_iter=2, wait_time=2)
        self.assertEqual(result, 2)

    def test_scan_swing(self):
        runner = CliRunner()
        result = runner.invoke(
            scan,
            args=[
                "--stocks",
                "BANDHANBNK,HDFC",
                "--swing",
                "--indicator",
                "all",
                "--clear",
                "--analyse",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Swing scanning finished.", result.output, str(result.output))

    def test_scan_swing_background(self):
        s = scannerFactory.scanner(ScannerType.Swing, ["HDFC"], "emac", True)
        scannerinstance = scanner(indicator="rsi")
        result = s.scan_background(scannerinstance, terminate_after_iter=2, wait_time=0)
        self.assertEqual(result, 0)
        self.assertFalse(s.background)

    def test_scan_volume(self):
        runner = CliRunner()
        result = runner.invoke(
            scan,
            args=[
                "--stocks",
                "BANDHANBNK",
                "--volume",
                "--clear",
                "--orderby",
                "TDYVol(%)",
                "--analyse",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Volume scanning finished.", result.output, str(result.output))

    def test_scan_volume_intraday(self):
        runner = CliRunner()
        result = runner.invoke(
            scan,
            args=[
                "--stocks",
                "BANDHANBNK",
                "--volume",
                "--clear",
                "--orderby",
                "TDYVol(%)",
                "--analyse",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Volume scanning finished.", result.output, str(result.output))

    def test_scan_volume_background(self):
        s = scannerFactory.scanner(ScannerType.Volume, ["HDFC"], "emac", True)
        scannerinstance = scanner(indicator="rsi")
        result = s.scan_background(scannerinstance, terminate_after_iter=2, wait_time=2)
        self.assertEqual(result, 2)

    def test_live_quote_inputs(self):
        runner = CliRunner()
        result = runner.invoke(live_quote, args=["-gowvb"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

    def test_news(self):
        runner = CliRunner()
        result = runner.invoke(
            news, args=["--stocks", "BANDHANBNK,ICICIBANK,ESCORTS,FSL,TCS,OIL,MOIL,ABB,ACC,DLF"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("News scanning finished", result.output, str(result.output))

    def test_top_picks(self):
        runner = CliRunner()
        result = runner.invoke(
            top_picks,
            args=[
                "--stocks",
                "BANDHANBNK,ICICIBANK,ESCORTS,FSL,TCS,OIL,MOIL,ABB,ACC,DLF",
                "--intraday",
                "--indicator",
                "macd",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("TopPick scanning finished", result.output, str(result.output))

    def test_scan_live_quote_background(self):
        scanner = scannerFactory.scanner(ScannerType.Quote)
        result = scanner.live_quote_background(
            "HDFC", True, True, True, True, True, terminate_after_iter=2, wait_time=2
        )
        self.assertEqual(result, 2)

    def test_scan_inputs(self):
        runner = CliRunner()
        result = runner.invoke(
            scan,
            args=[
                "--stocks",
                "BANDHANBNK,HDFC",
                "--swing",
                "--intraday",
                "--indicator",
                "all",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Choose only one of --live, --intraday, --swing or --volume options.",
            result.output,
            str(result.output),
        )
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

        result = runner.invoke(
            scan, args=["--stocks", "BANDHANBNK,HDFC", "--indicator", "all", "--clear"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Choose at least one of the --live, --intraday, --swing or --volume options.",
            result.output,
            str(result.output),
        )
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

        result = runner.invoke(
            top_picks, args=["--stocks", "BANDHANBNK,HDFC", "--indicator", "all", "--clear"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Choose at least one of the --intraday or --swing options.",
            result.output,
            str(result.output),
        )
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

        result = runner.invoke(
            top_picks,
            args=[
                "--stocks",
                "BANDHANBNK,HDFC",
                "--swing",
                "--intraday",
                "--indicator",
                "all",
                "--clear",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn(
            "Choose only one of --intraday or --swing options.", result.output, str(result.output)
        )
        self.assertIn("Usage:  [OPTIONS]", result.output, str(result.output))

    def test_scan_base_background(self):
        scanner_type = ScannerType.Intraday
        s = scannerFactory.scanner(scanner_type, ["HDFC"], "rsi", True)
        b = threading.Thread(
            name="scan_test_background", target=s.scan, args=["Symbol"], daemon=True
        )
        b.start()
        time.sleep(0.1)
        s.scan_background_interrupt()
        b.join()
        self.assertIn(f"This run of {scanner_type.name} scan took", self.capturedOutput.getvalue())
        self.assertIn(
            f"Finished all iterations of scanning {scanner_type.name}",
            self.capturedOutput.getvalue(),
        )

    def test_scan_background_None_instance(self):
        scanner = scannerFactory.scanner(ScannerType.Intraday)
        scanner.scan_background(None, terminate_after_iter=2, wait_time=2)
        self.assertIn(
            "Finished all iterations of scanning Intraday.", self.capturedOutput.getvalue()
        )

    def tearDown(self):
        super().tearDown()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestLivecli)
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
