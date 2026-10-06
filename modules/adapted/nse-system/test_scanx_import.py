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

from scanx_import import (
    _apply,
    _snapshot_values,
    _zero_sentinel_fields,
)


class ScanXImportTests(unittest.TestCase):
    def _item(self, row):
        return {
            "scanx_name": "Example Co",
            "symbol": "EXAMPLE",
            "isin": "INE000A01000",
            "company_name": "Example Company Limited",
            "match_method": "normalized_exact",
            "row": row,
        }

    def test_sentinel_and_outlier_values_are_audited_but_not_promoted(self):
        row = {
            "Name": "Example Co",
            "Payout Ratio": "0",
            "Change in promoter holding": "0",
            "Average ROE 3Years": "14.2",
            "ROE Growth % (5 Year)": "5800",
            "YoY last Quarterly Sales Growth": "4266000",
            "Free Cash Flow": "1,234.50",
        }
        sentinel_fields = _zero_sentinel_fields([row])
        snapshot = _snapshot_values(self._item(row), "2026-09-26", sentinel_fields)
        flags = set(json.loads(snapshot["data_quality_flags"]))

        self.assertEqual(sentinel_fields, {"Payout Ratio", "Change in promoter holding"})
        self.assertIsNone(snapshot["payout_ratio"])
        self.assertIsNone(snapshot["promoter_holding_change"])
        self.assertEqual(snapshot["roe_avg_3y"], 14.2)
        self.assertIsNone(snapshot["roe_growth_5y"])
        self.assertIsNone(snapshot["quarter_sales_yoy_growth"])
        self.assertEqual(snapshot["free_cash_flow"], 1234.5)
        self.assertIn("out_of_range:roe_growth_5y", flags)
        self.assertIn("out_of_range:quarter_sales_yoy_growth", flags)
        self.assertIn("unavailable_sentinel:payout_ratio", flags)
        self.assertEqual(json.loads(snapshot["raw_json"]), row)
        self.assertIsNone(snapshot["financial_period_end"])
        self.assertIsNone(snapshot["published_at"])

    def test_import_migrates_snapshots_without_mutating_fundamentals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "test.db"
            source_file = Path(temp_dir) / "scanx.csv"
            master_file = Path(temp_dir) / "master.csv"
            with source_file.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Name", "Free Cash Flow"])
                writer.writerow(["Example Co", "500"])
            with master_file.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER"])
                writer.writerow(["EXAMPLE", "Example Company Limited", "EQ", "INE000A01000"])
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE fundamentals (
                    symbol TEXT PRIMARY KEY,
                    pe REAL,
                    uploaded_at TEXT
                );
                INSERT INTO fundamentals VALUES ('EXAMPLE', 12.5, 'legacy');
                CREATE TABLE scanx_fundamentals_snapshots (
                    as_of_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT,
                    scanx_name TEXT,
                    company_name TEXT,
                    sector TEXT,
                    current_price REAL,
                    market_cap_cr REAL,
                    pe REAL,
                    pb REAL,
                    roe REAL,
                    roce REAL,
                    debt_to_equity REAL,
                    operating_margin REAL,
                    net_profit_margin REAL,
                    promoter_holding REAL,
                    fii_holding REAL,
                    dii_holding REAL,
                    dividend_yield REAL,
                    operating_cash_flow REAL,
                    cfo_positive INTEGER,
                    raw_json TEXT NOT NULL,
                    match_method TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (as_of_date, symbol)
                );
            """)
            conn.commit()
            conn.close()

            source_row = {
                "Name": "Example Co",
                "Average ROE 3Years": "14.2",
                "Free Cash Flow": "500",
            }
            snapshot = _snapshot_values(self._item(source_row), "2026-09-26")
            _apply(database, [snapshot], source_file, master_file)
            snapshot["free_cash_flow"] = 600
            _apply(database, [snapshot], source_file, master_file)

            conn = sqlite3.connect(database)
            self.assertEqual(
                conn.execute(
                    "SELECT pe, uploaded_at FROM fundamentals WHERE symbol='EXAMPLE'"
                ).fetchone(),
                (12.5, "legacy"),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM scanx_fundamentals_snapshots "
                    "WHERE as_of_date='2026-09-26'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT free_cash_flow, roe_avg_3y "
                    "FROM scanx_fundamentals_snapshots "
                    "WHERE as_of_date='2026-09-26'"
                ).fetchone(),
                (600.0, 14.2),
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(scanx_fundamentals_snapshots)")
            }
            self.assertIn("financial_period_end", columns)
            self.assertIn("data_quality_flags", columns)
            self.assertIn("source_sha256", columns)
            provenance = conn.execute(
                "SELECT source_sha256,security_master_sha256,"
                "source_modified_at FROM scanx_fundamentals_snapshots "
                "WHERE as_of_date='2026-09-26'"
            ).fetchone()
            self.assertRegex(provenance[0], r"^[0-9a-f]{64}$")
            self.assertRegex(provenance[1], r"^[0-9a-f]{64}$")
            self.assertIsNotNone(provenance[2])
            conn.close()


if __name__ == "__main__":
    unittest.main()
