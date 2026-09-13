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


"""CLI for local bootstrap and incremental daily NSE shareholding collection."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from nse_shareholding_collector import collect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--from-date", help="historical window start YYYY-MM-DD")
    parser.add_argument("--batch-days", type=int, default=31, help="historical window batch size")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--csv", type=Path, help="manual NSE listing CSV fallback/bootstrap")
    parser.add_argument("--output", type=Path, help="compatibility argument; normalized output is managed atomically")
    parser.add_argument("--db")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    end = date.fromisoformat(args.as_of)
    start = date.fromisoformat(args.from_date) if args.from_date else None
    if start and start > end:
        parser.error("--from-date cannot be after --as-of")
    results = []
    while start and start <= end:
        batch_end = min(start + timedelta(days=args.batch_days - 1), end)
        results.append(
            collect(
                db_path=args.db,
                as_of=batch_end,
                start_date=start,
                days=args.days,
                csv_fallback=args.csv,
                limit=args.limit,
                output_path=args.output,
            )
        )
        start = batch_end + timedelta(days=1)
    if not results:
        results.append(
            collect(
                db_path=args.db,
                as_of=end,
                days=args.days,
                csv_fallback=args.csv,
                limit=args.limit,
                output_path=args.output,
            )
        )
    statuses = {item.status for item in results}
    overall = (
        "DEGRADED"
        if "DEGRADED" in statuses
        else (
            "FRESH"
            if "FRESH" in statuses
            else ("REUSED_LAST_VALID" if "REUSED_LAST_VALID" in statuses else "NO_NEW_FILINGS")
        )
    )
    payload = {"windows": [item.__dict__ for item in results], "status": overall}
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "FRESH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
