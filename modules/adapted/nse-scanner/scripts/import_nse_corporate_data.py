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


"""Import normalized, point-in-time NSE corporate CSV extracts."""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd
from v2.database import V2Database

SPECS = {
    "market-cap": ("market_cap_snapshots_v3", {"symbol", "as_of_date", "available_date", "market_cap_cr", "source"}),
    "shares": ("shares_outstanding_v3", {"symbol", "as_of_date", "available_date", "shares_outstanding", "source"}),
    "pledge": ("promoter_pledge_v3", {"symbol", "as_of_date", "available_date", "pledge_pct", "event_type", "source"}),
    "governance": (
        "governance_events_v3",
        {"symbol", "event_date", "available_date", "event_type", "severity", "source"},
    ),
    "shareholding": (
        "shareholding_patterns_v3",
        {"symbol", "as_of_date", "available_date", "shares_outstanding", "promoter_holding_pct", "source"},
    ),
    "corporate-actions": ("corporate_actions_v3", {"symbol", "ex_date", "available_date", "action_type", "source"}),
}


def import_rows(db_path: str, kind: str, csv_path: str) -> int:
    table, required = SPECS[kind]
    frame = pd.read_csv(csv_path).where(pd.notna, None)
    missing = required.difference(frame.columns)
    if missing:
        msg = f"{kind} CSV missing columns: {sorted(missing)}"
        raise ValueError(msg)
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    V2Database(db_path).ensure_v3_schema()
    with sqlite3.connect(db_path) as conn:
        allowed = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        columns = [c for c in frame.columns if c in allowed and c != "loaded_at"]
        conflict = {
            "market-cap": "symbol,as_of_date,source",
            "shares": "symbol,as_of_date,available_date",
            "pledge": "symbol,as_of_date,event_type",
            "governance": "symbol,event_date,event_type",
            "shareholding": "symbol,as_of_date",
            "corporate-actions": "symbol,ex_date,action_type",
        }[kind]
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c not in conflict.split(","))
        conn.executemany(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT({conflict}) DO UPDATE SET {updates}",
            [tuple(row[c] for c in columns) for _, row in frame.iterrows()],
        )
        if kind == "market-cap" and "symbol_master_v2" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            conn.execute("""UPDATE symbol_master_v2 SET
              market_cap_cr=(SELECT m.market_cap_cr FROM market_cap_snapshots_v3 m WHERE m.symbol=symbol_master_v2.symbol ORDER BY m.available_date DESC LIMIT 1),
              market_cap_as_of=(SELECT m.as_of_date FROM market_cap_snapshots_v3 m WHERE m.symbol=symbol_master_v2.symbol ORDER BY m.available_date DESC LIMIT 1),
              market_cap_source=(SELECT m.source FROM market_cap_snapshots_v3 m WHERE m.symbol=symbol_master_v2.symbol ORDER BY m.available_date DESC LIMIT 1)
              WHERE EXISTS (SELECT 1 FROM market_cap_snapshots_v3 m WHERE m.symbol=symbol_master_v2.symbol)""")
        if kind == "shareholding":
            conn.execute("""INSERT INTO shares_outstanding_v3
              (symbol,as_of_date,available_date,shares_outstanding,source,filing_id)
              SELECT symbol,as_of_date,available_date,shares_outstanding,source,filing_id
              FROM shareholding_patterns_v3 WHERE 1
              ON CONFLICT(symbol,as_of_date,available_date) DO UPDATE SET
              shares_outstanding=excluded.shares_outstanding,source=excluded.source,
              filing_id=excluded.filing_id""")
    return len(frame)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(SPECS))
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--db", default="nse_scanner.db")
    args = parser.parse_args()
    print(f"Imported {import_rows(args.db, args.kind, str(args.csv_path))} {args.kind} rows")


if __name__ == "__main__":
    main()
