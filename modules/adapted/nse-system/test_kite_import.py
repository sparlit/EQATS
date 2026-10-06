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


import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kite_import import _apply, _snapshot_rows


class KiteImportTests(unittest.TestCase):
    def _read_rows(self, path):
        with Path(path).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def _files(self, folder):
        folder = Path(folder)
        export = folder / "KITE.csv"
        master = folder / "master.csv"
        headers = [
            "Instrument",
            "Last Price",
            "Previous Close",
            "Day High",
            "Day Low",
            "Open",
            "Change %",
            "Debt to Equity",
            "Dividend Yield",
            "Free Cash Flow",
            "Market Cap (Cr)",
            "Profit Growth YoY (%)",
            "P/E Ratio",
            "Revenue Growth YoY (%)",
            "Return on Equity",
            "Sector",
            "Average Price",
            "Buy Quantity",
            "Sell Quantity",
            "Trade Value (Cr)",
            "Volume",
            "52 Week High",
            "52 Week Low",
        ]
        rows = [
            [
                "Example Industries Limited",
                "120",
                "118",
                "122",
                "117",
                "118",
                "1.69%",
                "0.5",
                "1.2",
                "500",
                "1200",
                "20",
                "18",
                "15",
                "14",
                "Industrials",
                "0",
                "0",
                "0",
                "0",
                "0",
                "140",
                "80",
            ],
            [
                "Example Industries Limited",
                "120",
                "118",
                "122",
                "117",
                "118",
                "1.69%",
                "0.5",
                "1.2",
                "500",
                "1200",
                "20",
                "18",
                "15",
                "14",
                "Industrials",
                "0",
                "0",
                "0",
                "0",
                "0",
                "140",
                "80",
            ],
            [
                "Unlisted Alias",
                "25",
                "24",
                "26",
                "23",
                "24",
                "4.17%",
                "0",
                "0",
                "10",
                "10",
                "-5",
                "8",
                "4",
                "3",
                "Unknown",
                "0",
                "0",
                "0",
                "0",
                "0",
                "30",
                "10",
            ],
        ]
        with export.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
        with master.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER"])
            writer.writerow(["EXAMPLE", "Example Industries Limited", "EQ", "INE000A01000"])
            writer.writerow(["ADANIENSOL", "Adani Energy Solutions Limited", "EQ", "INE000B01000"])
        return export, master

    def test_import_preserves_raw_rows_and_only_maps_exact_names(self):
        with tempfile.TemporaryDirectory() as directory:
            export, master = self._files(directory)
            source_rows = self._read_rows(export)
            snapshots, sentinels, count = _snapshot_rows(source_rows, master, "2026-09-26", export)

            self.assertEqual(count, 3)
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(
                sentinels,
                {"Average Price", "Buy Quantity", "Sell Quantity", "Trade Value (Cr)", "Volume"},
            )
            mapped = next(row for row in snapshots if row["symbol"])
            unmatched = next(row for row in snapshots if not row["symbol"])
            self.assertEqual(mapped["symbol"], "EXAMPLE")
            self.assertEqual(mapped["isin"], "INE000A01000")
            self.assertRegex(mapped["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(mapped["security_master_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(mapped["duplicate_row_count"], 2)
            self.assertIsNone(mapped["volume"])
            self.assertEqual(mapped["last_price"], 120)
            self.assertEqual(mapped["revenue_growth_yoy"], 15)
            self.assertIsNone(mapped["financial_period_end"])
            self.assertIsNone(mapped["published_at"])
            self.assertEqual(json.loads(mapped["raw_json"])["Volume"], "0")
            self.assertIsNone(unmatched["symbol"])
            self.assertEqual(unmatched["mapping_method"], "unmatched")
            self.assertEqual(unmatched["instrument"], "Unlisted Alias")

    def test_curated_abbreviation_matches_only_official_master_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            export, master = self._files(directory)
            source_row = self._read_rows(export)[0]
            source_row["Instrument"] = "ADANI ENERGY SOLUTION"

            snapshots, _, _ = _snapshot_rows([source_row], master, "2026-09-26", export)

            self.assertEqual(snapshots[0]["symbol"], "ADANIENSOL")
            self.assertEqual(snapshots[0]["mapping_method"], "curated_alias")
            self.assertEqual(snapshots[0]["company_name"], "Adani Energy Solutions Limited")

    def test_curated_alias_with_missing_master_symbol_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            export, master = self._files(directory)
            source_row = self._read_rows(export)[0]
            source_row["Instrument"] = "ADANI ENERGY SOLUTION"
            with master.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER"])
                writer.writerow(["EXAMPLE", "Example Industries Limited", "EQ", "INE000A01000"])
            with self.assertRaisesRegex(ValueError, "missing NSE security-master symbol"):
                _snapshot_rows([source_row], master, "2026-09-26", export)

    def test_import_is_idempotent_and_never_changes_live_fundamentals(self):
        with tempfile.TemporaryDirectory() as directory:
            export, master = self._files(directory)
            rows = self._read_rows(export)
            snapshots, _, _ = _snapshot_rows(rows, master, "2026-09-26", export)
            database = Path(directory) / "app.db"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE fundamentals (
                    symbol TEXT PRIMARY KEY,
                    pe REAL,
                    uploaded_at TEXT
                );
                INSERT INTO fundamentals VALUES ('EXAMPLE', 12.5, 'legacy');
            """)
            conn.close()

            self.assertEqual(_apply(database, snapshots), 2)
            snapshots[0]["last_price"] = 121
            self.assertEqual(_apply(database, snapshots), 2)
            conn = sqlite3.connect(database)
            self.assertEqual(
                conn.execute(
                    "SELECT pe, uploaded_at FROM fundamentals WHERE symbol='EXAMPLE'"
                ).fetchone(),
                (12.5, "legacy"),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM kite_market_snapshots").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute(
                    "SELECT last_price FROM kite_market_snapshots "
                    "WHERE instrument_key='exampleindustries'"
                ).fetchone()[0],
                121,
            )
            conn.close()

    def test_conflicting_duplicate_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            export, master = self._files(directory)
            rows = self._read_rows(export)
            rows[1]["Last Price"] = "121"
            with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
                _snapshot_rows(rows, master, "2026-09-26", export)


if __name__ == "__main__":
    unittest.main()
