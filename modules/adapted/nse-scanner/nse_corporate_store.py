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


"""Git-backed normalized corporate snapshots for disposable CI runners."""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path("corporate_data/normalized")
TABLES = {
    "symbol_master_v2": "symbol_master.csv",
    "shares_outstanding_v3": "shares_outstanding.csv",
    "market_cap_snapshots_v3": "market_cap_snapshots.csv",
    "promoter_pledge_v3": "promoter_pledge.csv",
    "governance_events_v3": "governance_events.csv",
    "shareholding_patterns_v3": "shareholding_patterns.csv",
    "corporate_actions_v3": "corporate_actions.csv",
}


def export_snapshots(db_path: str) -> dict[str, int]:
    ROOT.mkdir(parents=True, exist_ok=True)
    counts = {}
    with sqlite3.connect(db_path) as conn:
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, filename in TABLES.items():
            if table not in existing:
                continue
            frame = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            frame.to_csv(ROOT / filename, index=False, lineterminator="\n")
            counts[table] = len(frame)
    return counts


def restore_snapshots(db_path: str) -> dict[str, int]:
    counts = {}
    with sqlite3.connect(db_path) as conn:
        for table, filename in TABLES.items():
            path = ROOT / filename
            if not path.exists():
                continue
            frame = pd.read_csv(path)
            if frame.empty:
                counts[table] = 0
                continue
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            usable = [column for column in frame.columns if column in columns]
            placeholders = ",".join("?" for _ in usable)
            conn.executemany(
                f"INSERT OR REPLACE INTO {table} ({','.join(usable)}) VALUES ({placeholders})",
                [tuple(row[column] for column in usable) for _, row in frame.iterrows()],
            )
            counts[table] = len(frame)
        # Shares-outstanding is mechanically derived from the normalized
        # shareholding snapshot.  Recreate it on every disposable runner so
        # calculated market-cap coverage does not depend on a second CSV.
        if counts.get("shareholding_patterns_v3"):
            conn.execute("""INSERT INTO shares_outstanding_v3
                (symbol,as_of_date,available_date,shares_outstanding,source,filing_id)
                SELECT symbol,as_of_date,available_date,shares_outstanding,source,filing_id
                FROM shareholding_patterns_v3 WHERE 1
                ON CONFLICT(symbol,as_of_date,available_date) DO UPDATE SET
                  shares_outstanding=excluded.shares_outstanding,
                  source=excluded.source,filing_id=excluded.filing_id""")
            counts["shares_outstanding_v3"] = conn.execute("SELECT COUNT(*) FROM shares_outstanding_v3").fetchone()[0]
    return counts
