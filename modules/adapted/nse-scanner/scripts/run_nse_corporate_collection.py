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


"""Run corporate restore, collection, export and health reporting."""

import argparse
import json

from nse_corporate_collector import run_collection
from nse_corporate_store import export_snapshots, restore_snapshots
from v2.database import V2Database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--date", required=True)
    parser.add_argument("--market-cap-url")
    args = parser.parse_args()
    V2Database(args.db).ensure_v3_schema()
    restored = restore_snapshots(args.db)
    health = run_collection(args.db, args.date, args.market_cap_url)
    exported = export_snapshots(args.db)
    print(json.dumps({"restored": restored, "health": health, "exported": exported}, indent=2))
    return 0 if health["status"] in {"READY", "DEGRADED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
