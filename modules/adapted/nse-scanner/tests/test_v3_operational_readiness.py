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

from scripts.v3_operational_readiness import audit
from v2.database import V2Database


def test_gate_blocks_missing_index_and_market_cap(tmp_path):
    db = tmp_path / "readiness.db"
    sqlite3.connect(db).close()
    V2Database(db).ensure_v3_schema()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE daily_prices(symbol TEXT,date TEXT)")
        conn.executemany("INSERT INTO daily_prices VALUES ('ABC',?)", [(f"2026-01-{i:02d}",) for i in range(1, 10)])
    report = audit(str(db))
    assert report.status == "BLOCKED"
    assert "official_index_sessions_below_required" in report.blockers
    assert "market_cap_coverage_below_80_percent" in report.blockers


def test_gate_handles_empty_database(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    report = audit(str(db))
    assert report.status == "BLOCKED"
    assert report.blockers == ("price_table_missing",)
