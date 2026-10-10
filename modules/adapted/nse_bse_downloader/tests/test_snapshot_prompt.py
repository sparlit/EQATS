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


"""Phase 5 step 4: the rebuild prompt knows the database can repair too."""


import shutil
from datetime import date

import pandas as pd
from src.services.eod_store import EodStore
from src.services.history_revision import HistoryRevisionStore
from src.services.symbol_history import SymbolHistoryStore


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "SYMBOL": "ABC",
                "DATE": "20250101",
                "OPEN": 100,
                "HIGH": 100,
                "LOW": 100,
                "CLOSE": 100,
                "VOLUME": 10,
                "DELIVERY_QTY": 5,
                "DELIVERY_PERCENT": 50,
                "SERIES": "EQ",
                "TOTAL_TRADES": 1,
                "QTY_PER_TRADE": 10,
                "ISIN": "INE111111111",
                "SECURITY_ID": "500001",
            }
        ]
    )


def _upgraded_tree(root, *exchanges, mirror=True):
    """Symbol files an older build wrote, and no revision marker."""

    histories = SymbolHistoryStore(root)
    for exchange in exchanges:
        histories.upsert(exchange, "EQ", date(2025, 1, 1), _rows())
        if mirror:
            EodStore(root / ".state" / "eod.sqlite3", root / ".state" / "quarantine").upsert_frame(
                exchange, "EQ", _rows(), published=_rows()
            )
    (root / ".state" / "history_revision.json").unlink(missing_ok=True)
    (root / ".state" / "history_revision.json.bak").unlink(missing_ok=True)


def test_with_the_setting_off_nothing_about_the_prompt_changes(tmp_path):
    _upgraded_tree(tmp_path, "NSE", "BSE")
    shutil.rmtree(tmp_path / ".state" / "raw" / "BSE")

    lines = HistoryRevisionStore(tmp_path).notice().splitlines()

    assert len(lines) == 2
    assert ".state/raw" in lines[0] and "NSE" in lines[0]
    assert "BSE" in lines[1] and "cannot repair" in lines[1]


def test_the_database_makes_an_exchange_repairable_without_its_files(tmp_path):
    _upgraded_tree(tmp_path, "NSE", "BSE")
    shutil.rmtree(tmp_path / ".state" / "raw" / "BSE")

    lines = HistoryRevisionStore(tmp_path, snapshots_from_database=True).notice().splitlines()

    assert len(lines) == 1
    assert "BSE" in lines[0] and "NSE" in lines[0]
    assert "EOD database" in lines[0]


def test_no_files_and_no_database_rows_is_still_unrepairable(tmp_path):
    _upgraded_tree(tmp_path, "NSE", mirror=False)
    shutil.rmtree(tmp_path / ".state" / "raw" / "NSE")

    notice = HistoryRevisionStore(tmp_path, snapshots_from_database=True).notice()

    assert "cannot repair" in notice and "EOD database" in notice
