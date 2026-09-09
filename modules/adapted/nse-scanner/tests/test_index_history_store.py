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

from nse_market_store import export_index_history


def test_export_index_history(tmp_path, monkeypatch):
    db = tmp_path / "index.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE index_perf (
          id INTEGER PRIMARY KEY,index_name TEXT,date TEXT,open REAL,high REAL,
          low REAL,close REAL,UNIQUE(index_name,date))""")
        conn.execute(
            "INSERT INTO index_perf(index_name,date,open,high,low,close) VALUES ('NIFTY 50','2026-08-17',100,102,99,101)"
        )
    target = tmp_path / "index_history.csv"
    monkeypatch.setattr("nse_market_store.INDEX_HISTORY_PATH", target)
    assert export_index_history(db) == 1
    assert target.exists()
