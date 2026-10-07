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


"""Export journal data to CSV/JSON for analysis and backup.

Usage:
    python scripts/export_journal.py --format csv --output journal_export.csv
    python scripts/export_journal.py --format json --output journal_export.json
    python scripts/export_journal.py --format both --output journal_export
"""


import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa
from indian_quant.config.connections import get_engine


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if hasattr(obj, "__float__"):
            return float(obj)
        return super().default(obj)


def _fetch_all(engine, query: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text(query)).mappings().fetchall()
        return [dict(r) for r in rows]


def export_trade_journal(engine) -> list[dict]:
    return _fetch_all(
        engine,
        """
        SELECT * FROM trade_journal ORDER BY entry_date DESC
    """,
    )


def export_paper_signals(engine) -> list[dict]:
    return _fetch_all(
        engine,
        """
        SELECT * FROM paper_signals ORDER BY created_at DESC
    """,
    )


def export_unified(engine) -> list[dict]:
    return _fetch_all(
        engine,
        """
        SELECT * FROM v_all_trades ORDER BY entry_date DESC
    """,
    )


def export_hypothesis_trades(engine) -> list[dict]:
    return _fetch_all(
        engine,
        """
        SELECT * FROM hypothesis_trades ORDER BY created_at DESC
    """,
    )


def write_csv(data: list[dict], path: str) -> None:
    if not data:
        print("No data to export")
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"Exported {len(data)} rows to {path}")


def write_json(data: list[dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, cls=_Encoder, indent=2, default=str)
    print(f"Exported {len(data)} rows to {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export journal data")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="both")
    parser.add_argument("--output", default="journal_export")
    parser.add_argument(
        "--table", choices=["journal", "paper", "unified", "hypothesis", "all"], default="all"
    )
    args = parser.parse_args()

    engine = get_engine()
    exports = {}

    if args.table in ("journal", "all"):
        exports["trade_journal"] = export_trade_journal(engine)
    if args.table in ("paper", "all"):
        exports["paper_signals"] = export_paper_signals(engine)
    if args.table in ("unified", "all"):
        exports["unified_trades"] = export_unified(engine)
    if args.table in ("hypothesis", "all"):
        exports["hypothesis_trades"] = export_hypothesis_trades(engine)

    for name, data in exports.items():
        if args.format in ("csv", "both"):
            write_csv(data, f"{args.output}_{name}.csv")
        if args.format in ("json", "both"):
            write_json(data, f"{args.output}_{name}.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
