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

import nse_market_store


def test_blacklist_snapshot_is_exported_for_read_only_downstream_scanners(tmp_path, monkeypatch):
    monkeypatch.setattr(nse_market_store, "STORE_ROOT", tmp_path / "market_data")
    monkeypatch.setattr(nse_market_store, "BLACKLIST_PATH", tmp_path / "market_data" / "blacklist.csv")
    db_path = tmp_path / "scanner.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE blacklist (symbol TEXT, date TEXT, UNIQUE(symbol, date))")
        conn.execute("INSERT INTO blacklist VALUES ('ABC', '2026-08-20')")
    assert nse_market_store.export_blacklist_snapshot(db_path) == 1
    assert nse_market_store.BLACKLIST_PATH.read_text(encoding="utf-8").splitlines() == ["symbol,date", "ABC,2026-08-20"]
