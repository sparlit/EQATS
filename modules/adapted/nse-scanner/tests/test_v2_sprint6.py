from __future__ import annotations

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

from v2.health import build_health_report
from v2.index_ingestion import ingest_daily_index_snapshot, parse_index_snapshot
from v2.state_backup import create_state_backup, restore_state_backup

CSV = b"""Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Change(%)\nNIFTY 50,29-07-2026,25000,25200,24900,25150,0.60\nNIFTY 500,29-07-2026,23000,23100,22900,23080,0.35\n"""


def _seed_prices(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE daily_prices_v2(symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)"
        )
        conn.execute("INSERT INTO daily_prices_v2 VALUES ('ABC','2026-07-29',100,105,99,104,100000)")
        conn.execute("CREATE TABLE v2_positions(trade_id TEXT, state TEXT)")
        conn.execute("CREATE TABLE v2_position_events(event_id INTEGER)")
        conn.execute("CREATE TABLE v2_watchlist_memory(symbol TEXT, active INTEGER)")


def test_parse_and_ingest_snapshot(tmp_path):
    frame = parse_index_snapshot(CSV, expected_date="2026-07-29")
    assert set(frame["index_name"]) == {"NIFTY 50", "NIFTY 500"}
    db = tmp_path / "scanner.db"
    result = ingest_daily_index_snapshot(db, "2026-07-29", content=CSV, snapshot_dir=tmp_path / "snapshots")
    assert result.rows_upserted == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_perf").fetchone()[0] == 2


def test_snapshot_date_mismatch_rejected():
    try:
        parse_index_snapshot(CSV, expected_date="2026-07-28")
    except ValueError as exc:
        assert "date mismatch" in str(exc)
    else:
        msg = "expected date mismatch"
        raise AssertionError(msg)


def test_backup_restore_and_health(tmp_path):
    db = tmp_path / "scanner.db"
    _seed_prices(db)
    ingest_daily_index_snapshot(db, "2026-07-29", content=CSV, snapshot_dir=tmp_path / "snapshots")
    report = build_health_report(db, "2026-07-29")
    assert report.status == "HEALTHY"

    backup = create_state_backup(db, tmp_path / "backups")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM daily_prices_v2")
    restore_state_backup(backup.backup_path, db, expected_sha256=backup.sha256)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_prices_v2").fetchone()[0] == 1
