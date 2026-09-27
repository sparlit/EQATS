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


"""Sprint 8 command-line entry point.

The first implementation slice builds and persists the active-position review
queue. LLM, evidence and Telegram stages will be connected in later Sprint 8
sub-sprints without changing this interface.
"""


import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.portfolio_review import build_review_queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the monthly portfolio review queue")
    parser.add_argument("--portfolio", default="portfolio.json", help="Path to portfolio JSON")
    parser.add_argument("--period", default=None, help="Review period in YYYY-MM format")
    parser.add_argument(
        "--output",
        default="data/review_queue.json",
        help="Destination for the generated review queue",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue = build_review_queue(args.portfolio, args.period)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"Portfolio review queue created: {queue['count']} active symbols for {queue['review_period']} -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
