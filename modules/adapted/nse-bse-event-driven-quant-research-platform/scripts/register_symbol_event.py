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


"""Register a symbol lifecycle event (rename/suspension/delisting/migration).

Usage:
    python scripts/register_symbol_event.py --isin INE002A01018 --exchange NSE \
        --event RENAME --from OLD --to NEW --effective 2026-01-01
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.storage import MetadataStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a symbol event")
    parser.add_argument("--isin", required=True)
    parser.add_argument("--exchange", required=True)
    parser.add_argument("--event", required=True, choices=["RENAME", "SUSPENSION", "DELISTING", "SEGMENT_MIGRATION"])
    parser.add_argument("--effective", required=True, help="YYYY-MM-DD")
    parser.add_argument("--from", dest="from_symbol", default=None)
    parser.add_argument("--to", dest="to_symbol", default=None)
    parser.add_argument("--note", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    metadata = MetadataStore(settings.storage.metadata_dsn)
    event_id = metadata.record_symbol_event(
        isin=args.isin,
        exchange=args.exchange,
        event_type=args.event,
        effective_date=args.effective,
        from_symbol=args.from_symbol,
        to_symbol=args.to_symbol,
        note=args.note,
    )
    events = metadata.symbol_events_for_isin(args.isin)
    print(json.dumps({"recorded_event_id": event_id, "events_for_isin": len(events)}, indent=2))
    metadata.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
