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

import pandas as pd

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
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            grade TEXT,
            score REAL,
            rs_20d REAL,
            rs_60d REAL,
            close REAL,
            notes TEXT,
            status TEXT DEFAULT 'active',
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_calculations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry REAL,
            stop REAL,
            target REAL,
            capital REAL,
            shares INTEGER,
            risk_amount REAL,
            risk_pct REAL,
            reward REAL,
            rr_ratio REAL,
            passed INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def append_trade(trade: dict[str, Any]) -> None:
    """Append a trade entry to the database."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO trades (
            symbol, entry_price, exit_price, quantity, pnl, setup_type, notes,
            holding_period, side, planned_sl, planned_target, actual_rr,
            session_type, regime_at_entry, discipline_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.get("symbol"),
            trade.get("entry_price"),
            trade.get("exit_price"),
            trade.get("quantity"),
            trade.get("pnl"),
            trade.get("setup_type"),
            trade.get("notes"),
            trade.get("holding_period"),
            trade.get("side"),
            trade.get("planned_sl"),
            trade.get("planned_target"),
            trade.get("actual_rr"),
            trade.get("session_type"),
            trade.get("regime_at_entry"),
            trade.get("discipline_score"),
        ),
    )
    conn.commit()
    conn.close()


def get_trades(limit: int = 100) -> list[dict[str, Any]]:
    """Return trade history from the database."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, symbol, entry_price, exit_price, quantity, pnl, setup_type, notes, "
        "holding_period, side, planned_sl, planned_target, actual_rr, session_type, "
        "regime_at_entry, discipline_score, created_at "
        "FROM trades ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "symbol": row[1],
            "entry_price": row[2],
            "exit_price": row[3],
            "quantity": row[4],
            "pnl": row[5],
            "setup_type": row[6],
            "notes": row[7],
            "holding_period": row[8],
            "side": row[9],
            "planned_sl": row[10],
            "planned_target": row[11],
            "actual_rr": row[12],
            "session_type": row[13],
            "regime_at_entry": row[14],
            "discipline_score": row[15],
            "created_at": row[16],
        }
        for row in rows
    ]


def get_trades_df(limit: int = 100) -> pd.DataFrame:
    """Return trade history as a pandas DataFrame."""
    import pandas as pd

    trades = get_trades(limit=limit)
    if not trades:
        return pd.DataFrame(
            columns=[
                "id",
                "symbol",
                "entry_price",
                "exit_price",
                "quantity",
                "pnl",
                "setup_type",
                "notes",
                "holding_period",
                "side",
                "planned_sl",
                "planned_target",
                "actual_rr",
                "session_type",
                "regime_at_entry",
                "discipline_score",
                "created_at",
            ]
        )
    return pd.DataFrame(trades)


def get_tasks() -> list[dict[str, Any]]:
    """Return all tasks from the database."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, label, completed, context, created_at FROM tasks ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "label": row[1],
            "completed": bool(row[2]),
            "context": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def add_task(label: str, context: str | None = None) -> None:
    """Save a task item to the database."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (label, context) VALUES (?, ?)",
        (label, context),
    )
    conn.commit()
    conn.close()


# ── WATCHLIST ────────────────────────────────────────────────────


def add_to_watchlist(
    symbol: str, grade: str, score: float, rs_20d: float, rs_60d: float, close: float, notes: str
) -> None:
    """Add or replace a symbol in the watchlist."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
    cursor.execute(
        """INSERT INTO watchlist (symbol, grade, score, rs_20d, rs_60d, close, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (symbol, grade, score, rs_20d, rs_60d, close, notes),
    )
    conn.commit()
    conn.close()


def get_watchlist() -> list[dict[str, Any]]:
    """Return all active watchlist entries."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, symbol, grade, score, rs_20d, rs_60d, close, notes, status, added_at "
        "FROM watchlist WHERE status = 'active' ORDER BY score DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "symbol": r[1],
            "grade": r[2],
            "score": r[3],
            "rs_20d": r[4],
            "rs_60d": r[5],
            "close": r[6],
            "notes": r[7],
            "status": r[8],
            "added_at": r[9],
        }
        for r in rows
    ]


def remove_from_watchlist(symbol: str) -> None:
    """Mark a watchlist entry as removed."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE watchlist SET status = 'removed' WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()


def save_watchlist_from_screener(df: pd.DataFrame) -> int:
    """Bulk-save Grade A and B screener results to watchlist. Returns count saved."""
    eligible = df[df["grade"].isin(["A", "B"])] if "grade" in df.columns else pd.DataFrame()
    if eligible.empty:
        return 0
    count = 0
    for _, row in eligible.iterrows():
        add_to_watchlist(
            symbol=str(row.get("symbol", "")),
            grade=str(row.get("grade", "B")),
            score=float(row.get("score", 0)),
            rs_20d=float(row.get("rs_20d", 0)),
            rs_60d=float(row.get("rs_60d", 0)),
            close=float(row.get("close", 0)),
            notes=str(row.get("notes", ""))[:200],
        )
        count += 1
    return count


# ── RISK CALCULATIONS ────────────────────────────────────────────


def save_risk_calc(data: dict[str, Any]) -> None:
    """Persist a risk calculation to the database."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO risk_calculations
           (symbol, entry, stop, target, capital, shares, risk_amount,
            risk_pct, reward, rr_ratio, passed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("symbol", ""),
            data.get("entry"),
            data.get("stop"),
            data.get("target"),
            data.get("capital"),
            data.get("shares"),
            data.get("risk_amount"),
            data.get("risk_pct"),
            data.get("reward"),
            data.get("rr_ratio"),
            int(data.get("passed", False)),
        ),
    )
    conn.commit()
    conn.close()


def get_risk_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent risk calculations."""
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT symbol, entry, stop, target, shares, risk_amount, risk_pct, "
        "rr_ratio, passed, created_at FROM risk_calculations ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "symbol": r[0],
            "entry": r[1],
            "stop": r[2],
            "target": r[3],
            "shares": r[4],
            "risk_amount": r[5],
            "risk_pct": r[6],
            "rr_ratio": r[7],
            "passed": bool(r[8]),
            "created_at": r[9],
        }
        for r in rows
    ]
