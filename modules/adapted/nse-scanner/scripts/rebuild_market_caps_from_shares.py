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


"""Locally rebuild point-in-time market-cap snapshots from validated shares."""

import argparse
import sqlite3

from nse_corporate_collector import rebuild_caps_from_shares, refresh_current_market_cap
from v2.database import V2Database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    args = parser.parse_args()
    V2Database(args.db).ensure_v3_schema()
    with sqlite3.connect(args.db) as conn:
        rows = rebuild_caps_from_shares(conn, args.start_date, args.end_date)
        latest = args.end_date
        if not latest:
            table = (
                "daily_prices_v2"
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_prices_v2'").fetchone()
                else "daily_prices"
            )
            column = "trade_date" if table == "daily_prices_v2" else "date"
            latest = conn.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
        refreshed = refresh_current_market_cap(conn, latest) if latest else 0
    print({"market_cap_snapshots": rows, "current_symbol_master_rows": refreshed, "as_of": latest})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
