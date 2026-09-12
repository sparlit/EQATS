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


import unittest
from pathlib import Path

from context import NSE, get_last_working_date


class TestNseApiReportsH1(unittest.TestCase):
    """Tests NSE class report method with http1 using requests library"""

    @classmethod
    def setUpClass(cls):
        DIR = Path(__file__).parent
        cls.nse = NSE(DIR, server=False)
        cls.date = get_last_working_date()
        print(f"\nRunning tests for NSE reports using requests library and date: {cls.date:%d %b %Y, %H:%M}.\n")

    @classmethod
    def tearDownClass(cls):
        cls.nse.exit()

    def test_equityBhavcopy(self):
        file = self.nse.equityBhavcopy(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_deliveryBhavcopy(self):
        file = self.nse.deliveryBhavcopy(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_indicesBhavcopy(self):
        file = self.nse.indicesBhavcopy(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_pr_bhavcopy(self):
        file = self.nse.pr_bhavcopy(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".zip"

    def test_fnoBhavcopy(self):
        file = self.nse.fnoBhavcopy(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_pricebrand_report(self):
        file = self.nse.priceband_report(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_cm_mii_security_report(self):
        file = self.nse.cm_mii_security_report(date=self.date)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".csv"

    def test_download_document(self):
        url = "https://nsearchives.nseindia.com/annual_reports/AR_22445_HDFCBANK_2022_2023_19072023141052_07192023150000.zip"

        file = self.nse.download_document(url)

        exists = file.exists()
        file.unlink(missing_ok=True)

        assert exists
        assert file.suffix == ".pdf"


if __name__ == "__main__":
    unittest.main()
