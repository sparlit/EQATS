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


"""Read-only data-health gate for the isolated shadow engine."""

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd


def evaluate(db_path: str | Path, features: pd.DataFrame) -> dict:
    if features.empty:
        return {"status": "BLOCKED", "reasons": ["no_price_features"], "blocked_symbols": []}
    as_of = str(features["as_of_date"].iloc[0])
    reasons: list[str] = []
    blocked: list[str] = []
    if features["as_of_date"].nunique() != 1:
        reasons.append("mixed_as_of_dates")
    if features["close"].isna().any() or (features["close"] <= 0).any():
        reasons.append("invalid_close")
    try:
        with sqlite3.connect(str(db_path)) as conn:
            table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blacklist'").fetchone()
            if table:
                rows = conn.execute("SELECT DISTINCT symbol FROM blacklist WHERE date <= ?", (as_of,)).fetchall()
                blocked = sorted(str(row[0]) for row in rows)
    except sqlite3.Error:
        reasons.append("blacklist_unavailable")
    return {
        "status": "CURRENT" if not reasons else "DEGRADED",
        "as_of_date": as_of,
        "reasons": reasons,
        "blocked_symbols": blocked,
        "history_eligible": int((features["history_sessions"] >= 320).sum()),
    }
