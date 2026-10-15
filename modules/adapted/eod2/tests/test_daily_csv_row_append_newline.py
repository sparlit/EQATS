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
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from context import defs

HEADER = b"Date,Open,High,Low,Close,Volume,Series,TOTAL_TRADES,QTY_PER_TRADE,DLV_QTY\n"
ROW_1 = b"2024-05-01,1,1,1,1,100,EQ,10,10.0,50\n"
ROW_2 = b"2024-05-02,2,2,2,2,200,EQ,20,10.0,60\n"


class TestRollbackRowBoundaries(unittest.TestCase):
    """A rollback must leave every row newline terminated, so a row appended
    by the next sync starts on its own line instead of welding onto the
    previous row.
    """

    def setUp(self) -> None:
        with NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(HEADER + ROW_1 + ROW_2)
            self.tempfile = Path(f.name)

    def tearDown(self) -> None:
        self.tempfile.unlink()

    def test_rollback_preserves_trailing_newline(self):
        self.assertTrue(defs.delete_last_line_by_date(self.tempfile, "2024-05-02"))
        self.assertTrue(self.tempfile.read_bytes().endswith(b"\n"))

    def test_row_appended_after_rollback_starts_new_line(self):
        self.assertTrue(defs.delete_last_line_by_date(self.tempfile, "2024-05-02"))

        # mimics the next sync: update_nse_symbol appends the session row
        with patch.object(defs, "dates", SimpleNamespace(pandas_dt="2024-05-02", dt=None)):
            defs.update_nse_symbol(self.tempfile, "EQ", 2, 2, 2, 2, 200, 20, 60)

        df = pd.read_csv(self.tempfile)
        self.assertEqual(list(df["Date"]), ["2024-05-01", "2024-05-02"])


if __name__ == "__main__":
    unittest.main()
