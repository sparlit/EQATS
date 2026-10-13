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


import json
import sqlite3
import unittest

import db
from fundamentals_refresh import ALIASES, _upsert
from fundamentals_store import (
    flag_legacy_deprecated,
    integrity_report,
    merge,
)
from fundamentals_tv import _fundamentals_values


class FundamentalsIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(db.SCHEMA)
        db._migrate(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_merge_preserves_missing_fields_and_tracks_provenance(self):
        merge(
            self.conn,
            {
                "symbol": "EXAMPLE",
                "roe": 12,
                "pe": 18,
                "source_metadata": {"source_file": "first.csv"},
            },
            source="source_a",
            observed_at="2026-09-29",
        )
        merge(
            self.conn,
            {
                "symbol": "EXAMPLE",
                "roe": None,
                "pe": 20,
            },
            source="source_b",
            observed_at="2026-09-30",
        )

        row = self.conn.execute(
            "SELECT roe,pe,data_source,field_sources,field_updated_at,"
            "source_metadata FROM fundamentals WHERE symbol='EXAMPLE'"
        ).fetchone()
        self.assertEqual(row[:3], (12, 20, "source_b"))
        self.assertEqual(json.loads(row[3]), {"pe": "source_b", "roe": "source_a"})
        self.assertEqual(json.loads(row[4]), {"pe": "2026-09-30", "roe": "2026-09-29"})
        self.assertEqual(json.loads(row[5]), {"source_file": "first.csv"})

    def test_tradingview_roic_is_not_mislabeled_as_roce_or_cfo(self):
        values = _fundamentals_values(
            "EXAMPLE",
            {
                "close": 100,
                "book_value_per_share_fy": 50,
                "return_on_equity_fy": 12,
                "return_on_invested_capital_fy": 16,
                "free_cash_flow_fy": -5,
            },
            {},
            "2026-09-30T12:00:00+00:00",
        )

        self.assertEqual(values["roic"], 16)
        self.assertNotIn("roce", values)
        self.assertNotIn("cfo_positive", values)
        self.assertEqual(values["fcf_fy"], -5)

    def test_refresh_aliases_keep_roe_roce_roic_distinct(self):
        self.assertEqual(ALIASES["return_on_equity"], "roe")
        self.assertEqual(ALIASES["return_on_capital_employed"], "roce")
        self.assertEqual(ALIASES["return_on_invested_capital"], "roic")
        self.assertEqual(ALIASES["mcap_cr"], "market_cap_cr")

        _upsert(self.conn, {"symbol": "EXAMPLE", "roe": 14}, "fundamentals_csv")
        merge(self.conn, {"symbol": "EXAMPLE", "roce": 9, "roic": 11}, source="calculated")
        row = self.conn.execute(
            "SELECT roe,roce,roic FROM fundamentals WHERE symbol='EXAMPLE'"
        ).fetchone()
        self.assertEqual(row, (14, 9, 11))

    def test_integrity_report_flags_legacy_tradingview_proxy_values(self):
        merge(
            self.conn,
            {
                "symbol": "LEGACY",
                "roce": 15,
                "cfo_positive": 1,
            },
            source="tradingview",
        )
        report = integrity_report(self.conn)

        self.assertTrue(report["remediation_needed"])
        reasons = report["rows"][0]["reasons"]
        self.assertIn("cfo_positive may be an historical FCF sign proxy", reasons)
        self.assertIn("roce may contain return_on_invested_capital_fy", reasons)

    def test_integrity_report_marks_unattributed_legacy_rows(self):
        self.conn.execute(
            "INSERT INTO fundamentals(symbol, cfo_positive, fcf_fy) VALUES ('OLD', 1, 20.0)"
        )
        report = integrity_report(self.conn)
        old = {row["symbol"]: row["reasons"] for row in report["rows"]}
        self.assertIn("OLD", old)
        self.assertIn("legacy row has no field provenance", old["OLD"])

    def test_legacy_deprecation_preview_and_apply_are_safe_and_idempotent(self):
        self.conn.execute(
            "INSERT INTO fundamentals(symbol, cfo_positive, roce, "
            "data_quality_flags) VALUES ('OLD', 1, 13.0, "
            '\'{"flags":["reviewed"]}\')'
        )
        merge(
            self.conn,
            {
                "symbol": "TV",
                "cfo_positive": 1,
                "roce": 15.0,
            },
            source="tradingview",
            observed_at="2026-09-01",
        )
        merge(
            self.conn,
            {
                "symbol": "VERIFIED",
                "cfo_positive": 1,
                "roce": 12.0,
            },
            source="yahoo_financials",
            observed_at="2026-09-01",
        )
        merge(
            self.conn,
            {
                "symbol": "MIXED",
                "cfo_positive": 1,
            },
            source="yahoo_financials",
            observed_at="2026-09-01",
        )
        merge(
            self.conn,
            {
                "symbol": "MIXED",
                "pe": 10,
            },
            source="tradingview",
            observed_at="2026-09-02",
        )

        preview = flag_legacy_deprecated(self.conn)
        self.assertEqual(preview["candidate_count"], 2)
        self.assertEqual(preview["newly_flagged"], 0)
        self.assertEqual(preview["already_flagged"], 0)
        before = self.conn.execute(
            "SELECT cfo_positive,roce,data_quality_flags FROM fundamentals WHERE symbol='OLD'"
        ).fetchone()
        self.assertEqual(before[:2], (1, 13.0))
        self.assertIn("reviewed", json.loads(before[2])["flags"])

        applied = flag_legacy_deprecated(self.conn, apply=True)
        self.assertEqual(applied["newly_flagged"], 2)
        self.conn.commit()
        old = self.conn.execute(
            "SELECT cfo_positive,roce,data_quality_flags FROM fundamentals WHERE symbol='OLD'"
        ).fetchone()
        self.assertEqual(old[:2], (1, 13.0))
        self.assertEqual(set(json.loads(old[2])["flags"]), {"legacy_deprecated", "reviewed"})
        repeat = flag_legacy_deprecated(self.conn, apply=True)
        self.assertEqual(repeat["newly_flagged"], 0)
        self.assertEqual(repeat["already_flagged"], 2)
        self.assertNotIn("VERIFIED", {item["symbol"] for item in repeat["rows"]})
        self.assertNotIn("MIXED", {item["symbol"] for item in repeat["rows"]})


if __name__ == "__main__":
    unittest.main()
