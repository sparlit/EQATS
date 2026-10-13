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


import sqlite3
import tempfile
import unittest
from pathlib import Path

from kite_reconcile import reconcile, values_agree


class KiteReconcileTests(unittest.TestCase):
    def _database(self, folder):
        database = Path(folder) / "app.db"
        conn = sqlite3.connect(database)
        conn.executescript("""
            CREATE TABLE kite_market_snapshots (
                as_of_date TEXT,
                symbol TEXT,
                company_name TEXT,
                sector TEXT,
                source_modified_at TEXT,
                last_price REAL,
                market_cap_cr REAL,
                pe REAL,
                debt_to_equity REAL,
                dividend_yield REAL,
                roe REAL
            );
            CREATE TABLE scanx_fundamentals_snapshots (
                as_of_date TEXT,
                symbol TEXT,
                current_price REAL,
                market_cap_cr REAL,
                pe REAL,
                debt_to_equity REAL,
                dividend_yield REAL,
                roe REAL
            );
            CREATE TABLE fundamentals (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                sector TEXT,
                current_price REAL,
                market_cap_cr REAL,
                pe REAL,
                debt_to_equity REAL,
                dividend_yield REAL,
                roe REAL,
                uploaded_at TEXT,
                data_source TEXT
            );
            CREATE TABLE universe_broad (
                symbol TEXT PRIMARY KEY,
                close REAL,
                mcap_cr REAL
            );
            INSERT INTO kite_market_snapshots VALUES (
                '2026-09-26','EXAMPLE','Example Limited','Industry',
                '2026-09-26T23:00:00+05:30',100,1000,20,0.001,2,15
            );
            INSERT INTO scanx_fundamentals_snapshots VALUES (
                '2026-09-26','EXAMPLE',100,1005,22,0.002,2.01,15.1
            );
            INSERT INTO fundamentals VALUES (
                'EXAMPLE','Example Limited','Industry',90,900,18,
                0.004,1.5,14,'csv:2026-09-01T00:00:00','legacy'
            );
            INSERT INTO universe_broad VALUES ('EXAMPLE',90,900);
        """)
        conn.commit()
        conn.close()
        return database

    def test_relative_comparison_is_strict_around_zero(self):
        self.assertTrue(values_agree(0.001, 0.001005, 0.01))
        self.assertFalse(values_agree(0, 0.001, 0.01))
        self.assertTrue(values_agree(0, 0, 0.01))

    def test_attested_snapshot_does_not_overwrite_newer_daily_price(self):
        with tempfile.TemporaryDirectory() as folder:
            database = self._database(folder)
            conn = sqlite3.connect(database)
            conn.execute("CREATE TABLE prices_daily (symbol TEXT, date TEXT, close REAL)")
            conn.execute("INSERT INTO prices_daily VALUES ('EXAMPLE','2026-09-28',105)")
            conn.commit()
            conn.close()

            result = reconcile(database, apply=True, make_backup=False)

            self.assertEqual(result["newer_daily_price_symbols"], 1)
            self.assertEqual(result["newer_daily_close_updates_skipped"], 1)
            self.assertEqual(result["fields"]["current_price"]["stale_not_applied"], 1)
            conn = sqlite3.connect(database)
            self.assertEqual(
                conn.execute(
                    "SELECT current_price,market_cap_cr FROM fundamentals WHERE symbol='EXAMPLE'"
                ).fetchone(),
                (90, 1000),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT close,mcap_cr FROM universe_broad WHERE symbol='EXAMPLE'"
                ).fetchone(),
                (90, 1000),
            )
            stale_audit = conn.execute(
                "SELECT agreed,live_before,live_after,universe_before,"
                "universe_after,latest_daily_price_date,action "
                "FROM market_data_attestations WHERE field='current_price'"
            ).fetchone()
            self.assertEqual(
                stale_audit,
                (1, 90, 90, 90, 90, "2026-09-28", "attested_stale_snapshot_not_applied"),
            )
            conn.close()

    def test_only_attested_fields_update_live_and_universe_data(self):
        with tempfile.TemporaryDirectory() as folder:
            database = self._database(folder)
            result = reconcile(database, apply=True, make_backup=False)

            self.assertEqual(result["overlap_symbols"], 1)
            self.assertEqual(result["fundamentals_symbols_refreshed"], 1)
            conn = sqlite3.connect(database)
            live = conn.execute(
                "SELECT current_price,market_cap_cr,pe,debt_to_equity,"
                "dividend_yield,roe,data_source FROM fundamentals "
                "WHERE symbol='EXAMPLE'"
            ).fetchone()
            self.assertEqual(live, (100, 1000, 18, 0.004, 2, 15, "kite_scanx_attested"))
            broad = conn.execute(
                "SELECT close,mcap_cr FROM universe_broad WHERE symbol='EXAMPLE'"
            ).fetchone()
            self.assertEqual(broad, (100, 1000))
            audit = {
                row[0]: row[1:]
                for row in conn.execute(
                    "SELECT field,agreed,live_before,live_after,"
                    "universe_before,universe_after,action "
                    "FROM market_data_attestations"
                )
            }
            self.assertEqual(
                audit["current_price"], (1, 90, 100, 90, 100, "updated_fundamentals_and_universe")
            )
            self.assertEqual(audit["pe"][0], 0)
            self.assertEqual(audit["pe"][1:4], (18, 18, None))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM market_data_attestations").fetchone()[0], 6
            )
            conn.close()

            rerun = reconcile(database, apply=True, make_backup=False)
            self.assertEqual(rerun["fundamentals_symbols_refreshed"], 1)
            conn = sqlite3.connect(database)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM fundamentals WHERE symbol='EXAMPLE'").fetchone()[
                    0
                ],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM market_data_attestations").fetchone()[0], 6
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
