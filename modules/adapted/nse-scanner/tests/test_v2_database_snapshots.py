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
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from v2.database import V2Database
from v2.snapshots import build_market_snapshot, compute_breadth, persist_market_snapshot

if TYPE_CHECKING:
    from pathlib import Path


def seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE daily_prices (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, UNIQUE(symbol,date))"
    )
    rows = []
    dates = pd.bdate_range("2025-01-01", periods=220)
    for symbol, drift in [("AAA", 0.4), ("BBB", -0.05)]:
        for i, day in enumerate(dates):
            close = 100 + drift * i
            rows.append((symbol, day.date().isoformat(), close - 1, close + 1, close - 2, close, 100000 + i))
    conn.executemany("INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_database_adapter_reads_v1(tmp_path: Path):
    path = tmp_path / "sample.db"
    seed_db(path)
    frame = V2Database(path).load_prices(min_sessions=200)
    assert set(frame["symbol"]) == {"AAA", "BBB"}
    assert len(frame) == 440


def test_breadth_is_date_explicit(tmp_path: Path):
    path = tmp_path / "sample.db"
    seed_db(path)
    frame = V2Database(path).load_prices()
    result = compute_breadth(frame)
    assert result["eligible_200"] == 2
    assert result["as_of"] == frame["trade_date"].max().date().isoformat()


def test_snapshot_persistence_is_idempotent(tmp_path: Path):
    path = tmp_path / "sample.db"
    seed_db(path)
    prices = V2Database(path).load_prices()
    dates = pd.bdate_range("2025-01-01", periods=220)
    benchmark = pd.DataFrame({"trade_date": dates, "close": np.linspace(100, 180, len(dates))})
    snapshot = build_market_snapshot(prices, benchmark)
    persist_market_snapshot(path, snapshot)
    persist_market_snapshot(path, snapshot)
    conn = sqlite3.connect(path)
    count = conn.execute("SELECT COUNT(*) FROM market_regime_snapshots").fetchone()[0]
    conn.close()
    assert count == 1
