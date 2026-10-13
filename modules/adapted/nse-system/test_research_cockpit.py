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
import unittest
from unittest.mock import patch

import research_cockpit
from traders.base import select_scan_symbols


class ResearchCockpitTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE swing_signals (signal_date TEXT, symbol TEXT, mode TEXT)")
        self.conn.execute("CREATE TABLE trend_candidates (date TEXT, symbol TEXT, score REAL)")
        self.conn.execute(
            "CREATE TABLE prices_daily (symbol TEXT, date TEXT, open REAL, "
            "high REAL, low REAL, close REAL, volume REAL)"
        )
        self.conn.execute("CREATE TABLE stocks (symbol TEXT, sector TEXT)")
        self.conn.execute("CREATE TABLE universe_broad (symbol TEXT, mcap_cr REAL)")

    def tearDown(self):
        self.conn.close()

    def test_latest_scan_date_is_used_instead_of_machine_today(self):
        self.conn.executemany(
            "INSERT INTO swing_signals VALUES (?,?,?)",
            [("2026-10-01", "OLD", "SWING"), ("2026-10-02", "LATEST", "SWING")],
        )
        self.conn.executemany(
            "INSERT INTO trend_candidates VALUES (?,?,?)",
            [("2026-10-01", "OLDTREND", 1), ("2026-10-02", "LATESTTREND", 2)],
        )
        self.conn.execute(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?)",
            ("LATEST", "2026-10-02", 10, 12, 9, 11, 1000),
        )

        symbols = research_cockpit._today_symbols(self.conn)
        status = research_cockpit._source_status(research_cockpit._latest_scan_dates(self.conn))

        self.assertEqual(
            symbols,
            {
                "LATEST": "SWING",
                "LATESTTREND": "TREND",
            },
        )
        self.assertEqual(status["date"], "2026-10-02")
        self.assertFalse(status["stale"])

    def test_scan_freshness_is_visible_when_prices_are_newer(self):
        self.conn.execute(
            "INSERT INTO swing_signals VALUES (?,?,?)", ("2026-10-01", "TEST", "SWING")
        )
        self.conn.execute(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?)",
            ("TEST", "2026-10-02", 10, 12, 9, 11, 1000),
        )

        status = research_cockpit._source_status(research_cockpit._latest_scan_dates(self.conn))

        self.assertTrue(status["stale"])
        self.assertEqual(status["source_dates"]["prices"], "2026-10-02")

    def test_cached_research_is_invalidated_when_symbol_price_advances(self):
        self.conn.execute(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?)",
            ("TEST", "2026-10-01", 10, 12, 9, 11, 1000),
        )
        research_cockpit._put_cache(self.conn, "TEST", {"as_of": "2026-10-01"})
        self.assertIsNotNone(research_cockpit._get_cached(self.conn, "TEST"))

        self.conn.execute(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?)",
            ("TEST", "2026-10-02", 11, 13, 10, 12, 1100),
        )

        self.assertIsNone(research_cockpit._get_cached(self.conn, "TEST"))

    def test_targeted_scans_are_limited_to_the_existing_band_universe(self):
        self.conn.executemany(
            "INSERT INTO universe_broad VALUES (?,?)", [("ABC", 3000), ("MNO", 4500), ("XYZ", 9000)]
        )

        self.assertEqual(
            select_scan_symbols(self.conn, 800, [" abc ", "XYZ", "NOT_LISTED"]), ["ABC"]
        )
        self.assertEqual(select_scan_symbols(self.conn, 800), ["ABC", "MNO"])

    def test_partial_price_history_can_be_loaded_for_current_state(self):
        self.conn.executemany(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?)",
            [("TEST", f"2026-01-0{i}", 10, 12, 9, 11, 1000) for i in range(1, 6)],
        )

        with patch.object(research_cockpit.db, "get_conn", return_value=self.conn):
            result = research_cockpit.analyze_symbol("TEST", use_cache=False)

        self.assertEqual(result["history_bars_tested"], 5)
        self.assertFalse(result["history_sufficient"])
        self.assertEqual(result["market_state"]["close"], 11)
        self.assertIsNone(result["historical"]["p_trigger"])


if __name__ == "__main__":
    unittest.main()
