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


"""Non-mutating daily comparison of V2-compatible and strict-V3 universes."""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from v2.database import V2Database
from v2.eligibility import evaluate_eligibility


def compare(db_path: str, as_of: str | None = None) -> dict:
    """Evaluate both policies without writing the database, files, or portfolio state."""
    trade_date = as_of or date.today().isoformat()
    database = V2Database(db_path)
    prices = database.load_prices(end_date=trade_date, min_sessions=260)
    master = database.load_symbol_master(trade_date)
    metadata = {str(row.symbol): row.to_dict() for _, row in master.iterrows()}
    restricted = database.load_restricted_symbols(trade_date)
    v2, v3, newly_excluded = set(), set(), Counter()
    for symbol, frame in prices.groupby("symbol"):
        common = {
            "metadata": metadata.get(str(symbol)),
            "restricted_reason": restricted.get(str(symbol)),
            "as_of_date": trade_date,
        }
        compatible = evaluate_eligibility(str(symbol), frame, require_market_cap=False, **common)
        strict = evaluate_eligibility(
            str(symbol),
            frame,
            require_market_cap=True,
            require_promoter_holding=True,
            require_corporate_action_safety=True,
            **common,
        )
        if compatible.eligible:
            v2.add(str(symbol))
        if strict.eligible:
            v3.add(str(symbol))
        if compatible.eligible and not strict.eligible:
            newly_excluded[strict.reason_code] += 1
    return {
        "as_of_date": trade_date,
        "mutated": False,
        "v2_compatible_eligible": len(v2),
        "v3_strict_eligible": len(v3),
        "v3_only_exclusions": dict(sorted(newly_excluded.items())),
        "v2_only_symbols": sorted(v2 - v3),
        "v3_only_symbols": sorted(v3 - v2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--as-of")
    parser.add_argument("--output", default="output/v2_v3_eligibility_comparison.json")
    args = parser.parse_args()
    report = compare(args.db, args.as_of)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
