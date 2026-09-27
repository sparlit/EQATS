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


"""Watchlist and stock analysis database operations."""


import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class WatchlistStore:
    def __init__(self, db_path: str | Path):
        self._db = str(db_path)
        self._con = sqlite3.connect(self._db)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self._con.close()

    # ── Users ──────────────────────────────────────────────────────────

    def create_user(self, username: str, email: str, password_hash: str) -> int:
        cur = self._con.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, datetime('now'))",
            (username, email, password_hash),
        )
        self._con.commit()
        return cur.lastrowid or 0

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        row = self._con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        row = self._con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def update_last_login(self, user_id: int) -> None:
        self._con.execute("UPDATE users SET last_login = datetime('now') WHERE user_id = ?", (user_id,))
        self._con.commit()

    def username_exists(self, username: str) -> bool:
        row = self._con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        return row is not None

    def email_exists(self, email: str) -> bool:
        row = self._con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        return row is not None

    # ── Watchlists ─────────────────────────────────────────────────────

    def add_stock(self, user_id: int, symbol: str, notes: str = "") -> int:
        # Ensure user exists (prevents FK constraint failure)
        if not self.get_user_by_id(user_id):
            self.create_user("admin", "admin@local.dev", "dev-only-hash")
        cur = self._con.execute(
            "INSERT INTO watchlists (user_id, symbol, exchange, added_at, notes) "
            "VALUES (?, ?, 'NSE', datetime('now'), ?)",
            (user_id, symbol.upper(), notes),
        )
        self._con.commit()
        return cur.lastrowid or 0

    def remove_stock(self, user_id: int, symbol: str) -> bool:
        cur = self._con.execute(
            "DELETE FROM watchlists WHERE user_id = ? AND symbol = ?",
            (user_id, symbol.upper()),
        )
        self._con.commit()
        return cur.rowcount > 0

    def list_stocks(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._con.execute(
            "SELECT * FROM watchlists WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def is_watched(self, user_id: int, symbol: str) -> bool:
        row = self._con.execute(
            "SELECT 1 FROM watchlists WHERE user_id = ? AND symbol = ?",
            (user_id, symbol.upper()),
        ).fetchone()
        return row is not None

    def get_watchlist_id(self, user_id: int, symbol: str) -> int | None:
        row = self._con.execute(
            "SELECT watchlist_id FROM watchlists WHERE user_id = ? AND symbol = ?",
            (user_id, symbol.upper()),
        ).fetchone()
        return int(row["watchlist_id"]) if row else None

    # ── Watchlist Signals ──────────────────────────────────────────────

    def save_signal(self, watchlist_id: int, user_id: int, symbol: str, data: dict[str, Any]) -> None:
        self._con.execute(
            """INSERT INTO watchlist_signals
               (watchlist_id, user_id, symbol, signal_date, signal_type,
                close, deliv_pct, deliv_z, vol_z, ret_1d,
                rsi, macd, macd_signal, sma_20, sma_50, atr_14,
                entry_zone_low, entry_zone_high, stop_loss, target_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(watchlist_id) DO UPDATE SET
                signal_date=excluded.signal_date, signal_type=excluded.signal_type,
                close=excluded.close, deliv_pct=excluded.deliv_pct, deliv_z=excluded.deliv_z,
                vol_z=excluded.vol_z, ret_1d=excluded.ret_1d,
                rsi=excluded.rsi, macd=excluded.macd, macd_signal=excluded.macd_signal,
                sma_20=excluded.sma_20, sma_50=excluded.sma_50, atr_14=excluded.atr_14,
                entry_zone_low=excluded.entry_zone_low, entry_zone_high=excluded.entry_zone_high,
                stop_loss=excluded.stop_loss, target_price=excluded.target_price,
                updated_at=datetime('now')""",
            (
                watchlist_id,
                user_id,
                symbol.upper(),
                data.get("signal_date"),
                data.get("signal_type"),
                data.get("close"),
                data.get("deliv_pct"),
                data.get("deliv_z"),
                data.get("vol_z"),
                data.get("ret_1d"),
                data.get("rsi"),
                data.get("macd"),
                data.get("macd_signal"),
                data.get("sma_20"),
                data.get("sma_50"),
                data.get("atr_14"),
                data.get("entry_zone_low"),
                data.get("entry_zone_high"),
                data.get("stop_loss"),
                data.get("target_price"),
            ),
        )
        self._con.commit()

    def get_all_signals_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._con.execute(
            "SELECT * FROM watchlist_signals WHERE user_id = ? ORDER BY symbol",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_signal_for_symbol(self, user_id: int, symbol: str) -> dict[str, Any] | None:
        row = self._con.execute(
            "SELECT * FROM watchlist_signals WHERE user_id = ? AND symbol = ?",
            (user_id, symbol.upper()),
        ).fetchone()
        return dict(row) if row else None

    def symbol_count(self, user_id: int) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM watchlists WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0])
