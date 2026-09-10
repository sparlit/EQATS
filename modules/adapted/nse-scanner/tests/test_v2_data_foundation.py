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


import importlib.util
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def build_v1_fixture(db_path: Path, sessions: int = 400) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE daily_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            prev_close REAL, open REAL, high REAL, low REAL,
            last_price REAL, close REAL NOT NULL,
            avg_price REAL, volume INTEGER,
            turnover_lacs REAL, trades INTEGER,
            delivery_qty INTEGER, delivery_pct REAL,
            UNIQUE(symbol, date))"""
    )
    start = date(2024, 1, 1)
    for i in range(sessions):
        day = (start + timedelta(days=i)).isoformat()
        base = 100.0 + i / 10
        conn.execute(
            """INSERT INTO daily_prices (
                symbol, date, prev_close, open, high, low, last_price, close,
                avg_price, volume, turnover_lacs, trades, delivery_qty, delivery_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "TEST",
                day,
                base - 1,
                base,
                base + 2,
                base - 2,
                base + 0.5,
                base + 1,
                base,
                100000,
                500.0,
                1000,
                50000,
                50.0,
            ),
        )
    conn.commit()
    conn.close()


def test_audit_passes_valid_400_session_fixture(tmp_path: Path):
    db_path = tmp_path / "fixture.db"
    build_v1_fixture(db_path)
    audit = load_module("audit_nse_database", ROOT / "scripts" / "audit_nse_database.py")
    report = audit.audit_database(db_path)
    assert report["status"] == "PASS"
    assert report["metrics"]["session_count"] == 400


def test_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "fixture.db"
    build_v1_fixture(db_path, sessions=100)
    migration = load_module("migrate_v1_prices_to_v2", ROOT / "scripts" / "migrate_v1_prices_to_v2.py")
    schema = ROOT / "migrations" / "v2" / "001_data_foundation.sql"
    first = migration.migrate(db_path, schema)
    second = migration.migrate(db_path, schema)
    assert first["source_rows"] == first["target_rows"]
    assert second["source_rows"] == second["target_rows"]


def test_migration_blocks_invalid_ohlc(tmp_path: Path):
    db_path = tmp_path / "fixture.db"
    build_v1_fixture(db_path, sessions=1)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE daily_prices SET high = 90, low = 110")
    conn.commit()
    conn.close()

    migration = load_module(
        "migrate_v1_prices_to_v2_invalid",
        ROOT / "scripts" / "migrate_v1_prices_to_v2.py",
    )
    schema = ROOT / "migrations" / "v2" / "001_data_foundation.sql"
    try:
        migration.migrate(db_path, schema)
    except ValueError as exc:
        assert "invalid daily_prices rows" in str(exc)
    else:
        msg = "Invalid OHLC data should block migration"
        raise AssertionError(msg)
