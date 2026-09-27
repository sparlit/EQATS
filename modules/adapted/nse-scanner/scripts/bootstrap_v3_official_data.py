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


"""One-command local bootstrap for the 18-Aug-2026 V3 data load."""

import argparse
import json
from pathlib import Path

from nse_corporate_collector import run_collection
from nse_corporate_store import export_snapshots, restore_snapshots
from nse_loader import init_database
from nse_market_store import restore_prices
from scripts.backfill_nse_index_history import backfill
from scripts.import_nse_corporate_data import import_rows
from scripts.import_v3_fundamentals import import_fundamentals
from scripts.v3_operational_readiness import audit
from v2.database import V2Database

IMPORTS = {
    "market_cap.csv": "market-cap",
    "shareholding.csv": "shareholding",
    "shares_outstanding.csv": "shares",
    "pledge_encumbrance.csv": "pledge",
    "corporate_actions.csv": "corporate-actions",
    "governance_events.csv": "governance",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore, backfill, import and audit V3 official data")
    parser.add_argument("--date", required=True, help="Completed NSE session YYYY-MM-DD")
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--input-dir", default="manual_import")
    parser.add_argument("--skip-index-backfill", action="store_true")
    args = parser.parse_args()
    init_database(args.db)
    restore_prices(args.db, min_days=1)
    V2Database(args.db).ensure_v3_schema()
    restored = restore_snapshots(args.db)
    index_result = (0, 0) if args.skip_index_backfill else backfill(args.db, 420)
    imported = {}
    root = Path(args.input_dir)
    for filename, kind in IMPORTS.items():
        path = root / filename
        if path.exists():
            imported[filename] = import_rows(args.db, kind, str(path))
    fundamentals = root / "fundamentals.csv"
    if fundamentals.exists():
        imported["fundamentals.csv"] = import_fundamentals(args.db, str(fundamentals))
    health = run_collection(args.db, args.date)
    exported = export_snapshots(args.db)
    readiness = audit(args.db, as_of=args.date)
    result = {
        "restored": restored,
        "index_loaded_failed": index_result,
        "imported": imported,
        "collector": health,
        "exported": exported,
        "readiness": readiness.__dict__,
    }
    Path("output").mkdir(exist_ok=True)
    Path("output/v3_bootstrap_result.json").write_text(json.dumps(result, indent=2, default=list), encoding="utf-8")
    Path("output/v3_operational_readiness.json").write_text(
        json.dumps(readiness.__dict__, indent=2, default=list), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, default=list))
    return 0 if readiness.status == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
