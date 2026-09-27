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


"""Read-only native audit plus opt-in isolated Penny/Ladder cohort accounting.

No source scanner is run and no message is sent. Signal files must match market
dates; dated positions must come from dated snapshots, never today's state.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portfolio_accounting.adapters import hull_snapshot, legacy_records, read_v3
from portfolio_accounting.service import update_portfolio, write_reports
from v2.database import V2Database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--hull-state", default="pine_hull_state.json")
    parser.add_argument("--penny-report", default="output/penny_microcap/daily.json")
    parser.add_argument("--ladder-report", default="output/old_nse_hull_daily.json")
    parser.add_argument("--ladder-legacy", default="old_nse_hull_paper_state.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--v3-capital", type=float, help="Recorded starting capital if no snapshot exists")
    args = parser.parse_args()
    out = Path(args.output)
    database = V2Database(args.db)
    results, errors = {}, {}
    for scanner in ("Hull", "V3", "Penny", "Momentum Ladder"):
        try:
            if scanner == "Hull":
                snapshot = hull_snapshot(json.loads(Path(args.hull_state).read_text(encoding="utf-8")))
            elif scanner == "V3":
                snapshot = read_v3(args.db, capital=args.v3_capital)
            else:
                source = args.penny_report if scanner == "Penny" else args.ladder_report
                report = json.loads(Path(source).read_text(encoding="utf-8"))
                snapshot = update_portfolio(
                    scanner,
                    report,
                    database,
                    out / ("penny.sqlite" if scanner == "Penny" else "momentum_ladder.sqlite"),
                    legacy=legacy_records(args.ladder_legacy) if scanner == "Momentum Ladder" else None,
                    provenance="OFFLINE_REVIEW_COHORT",
                )
            write_reports(snapshot, out)
            results[scanner] = {
                key: snapshot[key]
                for key in (
                    "as_of_date",
                    "open_positions",
                    "pending_setups",
                    "available_cash",
                    "total_pnl",
                    "equity",
                    "provenance",
                    "execution_model",
                    "warnings",
                    "reconciliation_residual",
                )
            }
        except (ValueError, KeyError, OSError) as exc:
            errors[scanner] = str(exc)
    out.mkdir(parents=True, exist_ok=True)
    audit = {"results": results, "errors": errors, "delivery": "NONE", "source_mutation": "NONE"}
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
