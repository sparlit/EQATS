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


"""
SQLite storage layer — candle cache + trade log.

Two responsibilities:
  1. Cache fetched candles so we don't re-hit yfinance on every backtest run.
  2. Persist every trade with full context for analytics and future ML use.

DB file: data/cache.db (auto-created on first use).
"""

import os
import sqlite3
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache.db")
IST = ZoneInfo("Asia/Kolkata")


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol    TEXT    NOT NULL,
                interval  TEXT    NOT NULL,
                timestamp TEXT    NOT NULL,
                open      REAL, high REAL, low REAL, close REAL,
                volume    INTEGER,
                PRIMARY KEY (symbol, interval, timestamp)
            );

            -- One row per simulated trade, fully self-describing
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT,
                symbol        TEXT,
                regime        TEXT,
                strategy      TEXT,
                entry_time    TEXT,
                exit_time     TEXT,
                entry_price   REAL,
                exit_price    REAL,
                sl_price      REAL,
                tp_price      REAL,
                shares        INTEGER,
                pnl           REAL,
                pnl_pct       REAL,
                exit_reason   TEXT,
                entry_reason  TEXT
            );

            -- Per-day summary for quick analytics queries
            CREATE TABLE IF NOT EXISTS daily_summary (
                date       TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                regime     TEXT,
                strategy   TEXT,
                trades     INTEGER,
                wins       INTEGER,
                pnl        REAL,
                PRIMARY KEY (date, symbol)
            );
        """)
        con.execute("""
            DELETE FROM trades
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM trades
                GROUP BY date, symbol, strategy, entry_time, exit_time,
                         entry_price, exit_price, shares, exit_reason
            )
        """)
        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_unique_run
            ON trades (
                date, symbol, strategy, entry_time, exit_time,
                entry_price, exit_price, shares, exit_reason
            )
        """)


# ── Candle cache ──────────────────────────────────────────────────────────────


def load_candles(symbol: str, date: str, interval: str):
    """
    Try to load a day's candles from cache.
    Returns None if not cached yet.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM candles WHERE symbol=? AND interval=? AND timestamp LIKE ? "
            "ORDER BY timestamp",
            (symbol, interval, f"{date}%"),
        ).fetchall()

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed").dt.tz_convert(IST)
    return df.set_index("timestamp")


def save_candles(symbol: str, interval: str, df: pd.DataFrame) -> None:
    """Cache OHLCV rows. Ignores duplicates (INSERT OR IGNORE)."""
    idx = pd.to_datetime(df.index, utc=True).tz_convert(IST)
    rows = [
        (symbol, interval, ts.isoformat(), row.open, row.high, row.low, row.close, int(row.volume))
        for ts, (_, row) in zip(idx, df.iterrows(), strict=False)
    ]
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO candles "
            "(symbol, interval, timestamp, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


# ── Trade log ─────────────────────────────────────────────────────────────────


def save_trades(trades: list[dict]) -> None:
    """Persist trades idempotently; repeated backtests should not duplicate rows."""
    if not trades:
        return
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO trades "
            "(date, symbol, regime, strategy, entry_time, exit_time, "
            " entry_price, exit_price, sl_price, tp_price, shares, "
            " pnl, pnl_pct, exit_reason, entry_reason) "
            "VALUES (:date,:symbol,:regime,:strategy,:entry_time,:exit_time,"
            ":entry_price,:exit_price,:sl_price,:tp_price,:shares,"
            ":pnl,:pnl_pct,:exit_reason,:entry_reason)",
            trades,
        )


def save_daily_summary(rows: list[dict]) -> None:
    with _conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO daily_summary "
            "(date, symbol, regime, strategy, trades, wins, pnl) "
            "VALUES (:date,:symbol,:regime,:strategy,:trades,:wins,:pnl)",
            rows,
        )


def load_trades(symbol: str | None = None, date_from: str | None = None, date_to: str | None = None) -> pd.DataFrame:
    """Load trades from the log with optional filters. Returns a DataFrame."""
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    if symbol:
        query += " AND symbol=?"
        params.append(symbol)
    if date_from:
        query += " AND date>=?"
        params.append(date_from)
    if date_to:
        query += " AND date<=?"
        params.append(date_to)
    query += " ORDER BY entry_time"

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])
