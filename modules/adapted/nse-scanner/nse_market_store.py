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


"""Git-backed normalized EOD market-data store for stateless runners.

GitHub Actions runners are disposable, so the local SQLite database cannot be
the source of truth. This module persists one compact CSV per trading day in
the repository and rebuilds a temporary SQLite database when a runner starts.
"""


import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

STORE_ROOT = Path("market_data")
DAILY_DIR = STORE_ROOT / "daily"
MANIFEST_PATH = STORE_ROOT / "manifest.json"
INDEX_HISTORY_PATH = STORE_ROOT / "index_history.csv"
BLACKLIST_PATH = STORE_ROOT / "blacklist.csv"
# Retain a fixed rolling window: each successful run adds the newest completed
# session and removes the oldest snapshot only after the window exceeds 420.
KEEP_DAYS = 420

PRICE_COLUMNS = [
    "symbol",
    "date",
    "prev_close",
    "open",
    "high",
    "low",
    "last_price",
    "close",
    "avg_price",
    "volume",
    "turnover_lacs",
    "trades",
    "delivery_qty",
    "delivery_pct",
]


def _snapshot_paths() -> list[Path]:
    return sorted(DAILY_DIR.glob("????-??-??.csv"))


def snapshot_dates() -> list[str]:
    return [path.stem for path in _snapshot_paths()]


def restore_prices(db_path: str | Path, min_days: int = 1) -> int:
    """Restore saved daily snapshots into an empty SQLite database."""
    paths = _snapshot_paths()
    if len(paths) < min_days:
        return 0

    conn = sqlite3.connect(str(db_path))
    restored = 0
    try:
        for path in paths[-KEEP_DAYS:]:
            day = path.stem
            existing = conn.execute("SELECT 1 FROM load_log WHERE date = ? AND status = 'ok'", (day,)).fetchone()
            if existing:
                continue

            frame = pd.read_csv(path)
            if frame.empty:
                continue
            missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
            if missing:
                msg = f"Invalid market snapshot {path}: missing {missing}"
                raise ValueError(msg)

            frame[PRICE_COLUMNS].to_sql("daily_prices", conn, if_exists="append", index=False)
            conn.execute(
                """INSERT OR REPLACE INTO load_log
                   (date, loaded_at, prices_rows, status, notes)
                   VALUES (?, ?, ?, 'ok', ?)""",
                (day, datetime.utcnow().isoformat(), len(frame), "Restored from market_data snapshot"),
            )
            restored += 1
        if INDEX_HISTORY_PATH.exists():
            indices = pd.read_csv(INDEX_HISTORY_PATH)
            required = ["index_name", "date", "open", "high", "low", "close"]
            if not indices.empty and all(column in indices for column in required):
                optional = [column for column in ("change_pct", "volume", "pe", "pb", "div_yield") if column in indices]
                columns = [*required, *optional]
                conn.executemany(
                    f"INSERT OR REPLACE INTO index_perf ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [tuple(row[column] for column in columns) for _, row in indices.iterrows()],
                )
        if BLACKLIST_PATH.exists():
            blacklist = pd.read_csv(BLACKLIST_PATH)
            if not blacklist.empty and {"symbol", "date"}.issubset(blacklist.columns):
                conn.executemany(
                    "INSERT OR IGNORE INTO blacklist (symbol, date) VALUES (?, ?)",
                    [
                        tuple(row)
                        for row in blacklist[["symbol", "date"]].drop_duplicates().itertuples(index=False, name=None)
                    ],
                )
        conn.commit()
    finally:
        conn.close()
    return restored


def export_price_snapshot(db_path: str | Path, trade_date: date | str) -> Path:
    """Write one normalized, version-control-friendly price snapshot."""
    day = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = DAILY_DIR / f"{day}.csv"

    conn = sqlite3.connect(str(db_path))
    try:
        frame = pd.read_sql_query(
            f"SELECT {', '.join(PRICE_COLUMNS)} FROM daily_prices WHERE date = ? ORDER BY symbol",
            conn,
            params=(day,),
        )
    finally:
        conn.close()

    if frame.empty:
        msg = f"Cannot create snapshot for {day}: no daily_prices rows"
        raise ValueError(msg)
    frame.to_csv(snapshot_path, index=False, lineterminator="\n")
    return snapshot_path


def export_all_price_snapshots(db_path: str | Path, keep_days: int = KEEP_DAYS) -> int:
    """Create missing snapshots for database history and prune old files."""
    conn = sqlite3.connect(str(db_path))
    try:
        dates = [
            row[0]
            for row in conn.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT ?", (keep_days,))
        ]
    finally:
        conn.close()

    written = 0
    for day in dates:
        path = DAILY_DIR / f"{day}.csv"
        if not path.exists():
            export_price_snapshot(db_path, day)
            written += 1

    paths = _snapshot_paths()
    for path in paths[:-keep_days]:
        path.unlink()
    write_manifest()
    export_index_history(db_path)
    export_blacklist_snapshot(db_path)
    return written


def export_index_history(db_path: str | Path, keep_sessions: int = KEEP_DAYS) -> int:
    """Persist official NSE index rows for regime and relative-strength replay."""
    with sqlite3.connect(str(db_path)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_perf'").fetchone()
        if not exists:
            return 0
        frame = pd.read_sql_query("SELECT * FROM index_perf ORDER BY date,index_name", conn)
    if frame.empty:
        return 0
    dates = sorted(frame["date"].astype(str).unique())[-keep_sessions:]
    frame = frame[frame["date"].astype(str).isin(dates)]
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(INDEX_HISTORY_PATH, index=False, lineterminator="\n")
    return len(frame)


def export_blacklist_snapshot(db_path: str | Path) -> int:
    """Persist surveillance exclusions once for all downstream read-only scanners."""
    with sqlite3.connect(str(db_path)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blacklist'").fetchone()
        if not exists:
            return 0
        frame = pd.read_sql_query("SELECT symbol, date FROM blacklist ORDER BY date, symbol", conn)
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(BLACKLIST_PATH, index=False, lineterminator="\n")
    return len(frame)


def write_manifest() -> None:
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    dates = snapshot_dates()
    payload = {
        "schema_version": 1,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "snapshot_count": len(dates),
        "oldest_date": dates[0] if dates else None,
        "newest_date": dates[-1] if dates else None,
        "columns": PRICE_COLUMNS,
    }
    pd.Series(payload).to_json(MANIFEST_PATH, indent=2)
