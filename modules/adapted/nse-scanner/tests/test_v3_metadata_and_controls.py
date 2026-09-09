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

import pandas as pd
from scripts.import_v3_symbol_metadata import import_metadata
from v2.candidates import _classification


def test_market_cap_importer_updates_symbol_master(tmp_path):
    db = tmp_path / "scanner.db"
    csv = tmp_path / "caps.csv"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE symbol_master_v2 (
            symbol TEXT PRIMARY KEY, series TEXT, active INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    pd.DataFrame(
        [
            {
                "symbol": "abc",
                "series": "eq",
                "market_cap_cr": 2500,
                "as_of_date": "2026-08-14",
            }
        ]
    ).to_csv(csv, index=False)
    assert import_metadata(str(db), str(csv)) == 1
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT symbol,series,market_cap_cr FROM symbol_master_v2").fetchone()
    assert row == ("ABC", "EQ", 2500.0)


class _Trigger:
    actionable = True


class _Plan:
    state = "READY"


def test_missing_official_benchmark_can_watch_but_not_action():
    class _Score:
        score = 85
        hard_blocks = ()

    scores = {"1M": _Score(), "3M": _Score(), "6M": _Score(), "12M": _Score()}
    assert _classification(scores, _Trigger(), _Plan(), stale_data=False, action_permitted=False) == "WATCH"
