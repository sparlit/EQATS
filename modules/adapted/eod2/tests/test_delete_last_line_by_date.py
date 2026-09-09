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
from tempfile import NamedTemporaryFile

from context import defs


class TestDeleteLastLineByDate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with NamedTemporaryFile(mode="w+", delete=False) as f:
            f.write("")
            cls.empty_file = Path(f.name)

        with NamedTemporaryFile(mode="w+", delete=False) as f:
            f.write("Date,Open,High,Low,Close")
            cls.str_only_file = Path(f.name)

    @classmethod
    def tearDownClass(cls):
        cls.empty_file.unlink()
        cls.str_only_file.unlink()

    def setUp(self) -> None:
        with NamedTemporaryFile(mode="w+", delete=False) as f:
            f.write("2024-05-01,1\n2024-05-02,1\n2024-05-03,1\n")
            self.tempfile = Path(f.name)

    def tearDown(self) -> None:
        self.tempfile.unlink()

    def test_date_found(self):
        assert defs.deleteLastLineByDate(self.tempfile, "2024-05-03")

        result = self.tempfile.read_text()
        assert result.strip() == "2024-05-01,1\n2024-05-02,1"

    def test_date_not_found(self):
        assert not defs.deleteLastLineByDate(self.tempfile, "2024-05-04")

    def test_empty_file(self):
        assert not defs.deleteLastLineByDate(self.empty_file, "2024-05-04")

    def test_file_string_no_date(self):

        assert not defs.deleteLastLineByDate(self.str_only_file, "2024-05-04")


if __name__ == "__main__":
    unittest.main()
