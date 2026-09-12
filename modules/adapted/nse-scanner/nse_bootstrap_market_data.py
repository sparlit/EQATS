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


"""Build Git-backed market-data snapshots from a validated NSE bootstrap.

This is a local setup tool.  It does not download data, run the scanner, or
send Telegram messages.  Raw NSE files remain ignored; only market_data/ is
intended to be committed.
"""


import argparse
import json
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from nse_loader import init_database, load_day
from nse_market_store import export_all_price_snapshots, snapshot_dates

DB_PATH = Path("nse_scanner.db")
MANIFEST_PATH = Path("nse_data/bootstrap_manifest.json")
REQUIRED_DAYS = 420


def read_valid_dates() -> list[date]:
    if not MANIFEST_PATH.exists():
        msg = f"Missing bootstrap manifest: {MANIFEST_PATH}"
        raise FileNotFoundError(msg)
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    dates = [date.fromisoformat(value) for value in payload.get("valid_dates", [])]
    if len(dates) < REQUIRED_DAYS:
        msg = f"Bootstrap has only {len(dates)} valid days; {REQUIRED_DAYS} are required."
        raise ValueError(msg)
    return sorted(dates)[-REQUIRED_DAYS:]


def archive_existing_database() -> None:
    if not DB_PATH.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.with_name(f"{DB_PATH.stem}.pre_bootstrap_{stamp}.db")
    shutil.move(str(DB_PATH), str(backup))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{DB_PATH}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    print(f"Archived previous local database: {backup.name}")


def distinct_price_days() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(DISTINCT date) FROM daily_prices").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert validated NSE bootstrap files to market_data snapshots.")
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Archive the existing local scanner database before loading the 420 validated sessions.",
    )
    args = parser.parse_args()

    if DB_PATH.exists() and not args.reset_db:
        msg = (
            "A local nse_scanner.db already exists. Re-run with --reset-db to archive it "
            "and build an exact 420-day bootstrap."
        )
        raise SystemExit(msg)

    dates = read_valid_dates()
    if args.reset_db:
        archive_existing_database()
    init_database()

    loaded = failed = 0
    for index, trade_date in enumerate(dates, start=1):
        result = load_day(trade_date, do_cleanup=False)
        if result["status"] in ("ok", "already_loaded"):
            loaded += 1
        else:
            failed += 1
            print(f"FAILED {trade_date}: {result['status']} | {result.get('errors', [])}")
        if index % 10 == 0 or index == len(dates):
            print(f"Progress: {index}/{len(dates)} (loaded={loaded}, failed={failed})")

    day_count = distinct_price_days()
    if failed or day_count != REQUIRED_DAYS:
        msg = f"Bootstrap load incomplete: {day_count}/{REQUIRED_DAYS} price days."
        raise SystemExit(msg)

    written = export_all_price_snapshots(DB_PATH, keep_days=REQUIRED_DAYS)
    snapshots = snapshot_dates()
    if len(snapshots) != REQUIRED_DAYS:
        msg = f"Snapshot export incomplete: {len(snapshots)}/{REQUIRED_DAYS} files."
        raise SystemExit(msg)

    print(f"Complete: {day_count} price days loaded; {written} snapshots written.")
    print(f"market_data range: {snapshots[0]} to {snapshots[-1]}")


if __name__ == "__main__":
    main()
