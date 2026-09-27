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


"""Persistent shadow lifecycle records, intentionally separate from Hull state."""

import sqlite3
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path


def init_schema(db_path: str | Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS old_nse_hull_multi_horizon_daily (
            as_of_date TEXT NOT NULL, symbol TEXT NOT NULL, primary_horizon TEXT,
            primary_score REAL NOT NULL, confluence_score REAL NOT NULL,
            principal_bucket TEXT NOT NULL, qualified INTEGER NOT NULL,
            confirming_horizons TEXT NOT NULL, PRIMARY KEY (as_of_date, symbol))""")


def record(db_path: str | Path, scored: pd.DataFrame, prior_scored: pd.DataFrame | None = None) -> pd.DataFrame:
    """Store point-in-time shadow observations and derive migration labels."""
    init_schema(db_path)
    columns = [
        "as_of_date",
        "symbol",
        "primary_horizon",
        "primary_score",
        "confluence_score",
        "principal_bucket",
        "qualified",
        "confirming_horizons",
    ]
    current = scored.loc[:, columns].copy()
    # The shared adapter can expose multiple raw rows for a symbol/session in
    # legacy imports. A shadow observation is explicitly one row per symbol
    # and completed EOD date, so collapse those defensively before persistence.
    current = current.drop_duplicates(["as_of_date", "symbol"], keep="last")
    current["confirming_horizons"] = current["confirming_horizons"].apply(",".join)
    current["qualified"] = current["qualified"].astype(int)
    with sqlite3.connect(str(db_path)) as conn:
        previous = pd.read_sql_query(
            """SELECT * FROM old_nse_hull_multi_horizon_daily
            WHERE as_of_date = (SELECT MAX(as_of_date) FROM old_nse_hull_multi_horizon_daily
                                WHERE as_of_date < ?)""",
            conn,
            params=[current["as_of_date"].iloc[0] if not current.empty else ""],
        )
        # A rerun for the same completed EOD session refreshes the shadow
        # observation rather than manufacturing a second lifecycle event.
        if not current.empty:
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(
                f"INSERT OR REPLACE INTO old_nse_hull_multi_horizon_daily ({','.join(columns)}) VALUES ({placeholders})",
                [tuple(row[column] for column in columns) for _, row in current.iterrows()],
            )
    # GitHub Actions reconstructs SQLite from the shared price snapshots. If
    # no locally persisted prior state exists, derive it point-in-time from
    # the immediately preceding completed session rather than mislabelling
    # every daily shadow run as FIRST_SEEN.
    if previous.empty and prior_scored is not None and not prior_scored.empty:
        previous = prior_scored.loc[:, columns].copy()
    previous = previous.set_index("symbol") if not previous.empty else previous

    def state(row: pd.Series) -> str:
        if previous.empty or row["symbol"] not in previous.index:
            return "FIRST_QUALIFIED" if row["qualified"] else "FIRST_SEEN"
        prior = previous.loc[row["symbol"]]
        if not row["qualified"] and prior["qualified"]:
            return "EXIT"
        if row["qualified"] and not prior["qualified"]:
            return "NEWLY_QUALIFIED"
        if row["primary_horizon"] != prior["primary_horizon"]:
            return "UPGRADED" if row["primary_score"] >= prior["primary_score"] else "DOWNGRADED"
        return "CARRY_FORWARD" if row["qualified"] else "RADAR"

    current["lifecycle_status"] = current.apply(state, axis=1)
    return current
