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


"""Import dated market-cap and NSE symbol metadata from a controlled CSV."""

import argparse
import sqlite3

import pandas as pd

REQUIRED = {"symbol", "series", "market_cap_cr", "as_of_date"}


def import_metadata(db_path: str, csv_path: str) -> int:
    frame = pd.read_csv(csv_path)
    missing = REQUIRED.difference(frame.columns)
    if missing:
        msg = f"metadata CSV missing columns: {sorted(missing)}"
        raise ValueError(msg)
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["series"] = frame["series"].astype(str).str.strip().str.upper()
    frame["market_cap_cr"] = pd.to_numeric(frame["market_cap_cr"], errors="raise")
    if (frame["market_cap_cr"] <= 0).any():
        msg = "market_cap_cr must be positive"
        raise ValueError(msg)
    if frame["symbol"].duplicated().any():
        msg = "metadata CSV contains duplicate symbols"
        raise ValueError(msg)
    rows = [
        (row.symbol, row.series, float(row.market_cap_cr), str(row.as_of_date), 1)
        for row in frame.itertuples(index=False)
    ]
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(symbol_master_v2)")}
        if "market_cap_cr" not in columns:
            conn.execute("ALTER TABLE symbol_master_v2 ADD COLUMN market_cap_cr REAL")
        if "market_cap_as_of" not in columns:
            conn.execute("ALTER TABLE symbol_master_v2 ADD COLUMN market_cap_as_of DATE")
        conn.executemany(
            """INSERT INTO symbol_master_v2
            (symbol,series,market_cap_cr,market_cap_as_of,active)
            VALUES (?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET series=excluded.series,
            market_cap_cr=excluded.market_cap_cr,market_cap_as_of=excluded.market_cap_as_of,
            active=excluded.active,updated_at=CURRENT_TIMESTAMP""",
            rows,
        )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--db", default="nse_scanner.db")
    args = parser.parse_args()
    print(f"Imported {import_metadata(args.db, args.csv_path)} symbol metadata rows")


if __name__ == "__main__":
    main()
