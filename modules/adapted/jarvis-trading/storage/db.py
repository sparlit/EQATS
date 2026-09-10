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
from pathlib import Path
from typing import Any

from config import ROOT

DATABASE_PATH = ROOT / "data" / "app.db"


def ensure_data_dir() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


def create_connection() -> sqlite3.Connection:
    """Create a SQLite connection to the app database."""
    ensure_data_dir()
    return sqlite3.connect(DATABASE_PATH)


_TRADE_EXTRA_COLUMNS = {
    "holding_period": "TEXT",
    "side": "TEXT",  # LONG / SHORT
    "planned_sl": "REAL",
    "planned_target": "REAL",
    "actual_rr": "REAL",
    "session_type": "TEXT",  # INTRADAY / SWING
    "regime_at_entry": "TEXT",  # BULLISH / NEUTRAL / BEARISH
    "discipline_score": "INTEGER",  # 1-10 self-rating
}


def _ensure_trade_schema(cursor: sqlite3.Cursor) -> None:
    """Add any missing journal columns (idempotent migration)."""
    cursor.execute("PRAGMA table_info(trades)")
    columns = [row[1] for row in cursor.fetchall()]
    for col, col_type in _TRADE_EXTRA_COLUMNS.items():
        if col not in columns:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")


def init_db() -> None:
    """Initialize application database tables."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity INTEGER,
            pnl REAL,
            setup_type TEXT,
            notes TEXT,
            holding_period TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_trade_schema(cursor)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            context TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS
"""