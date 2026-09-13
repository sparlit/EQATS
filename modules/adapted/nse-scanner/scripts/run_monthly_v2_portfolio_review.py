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


"""Run and persist the monthly V2 carry-forward portfolio review."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.monthly_portfolio import run_monthly_portfolio_review
from v2.state_file import export_state_file, restore_state_file
from v2.telegram_delivery import send_messages, topic_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--state-file", default="v2_portfolio_state.json")
    parser.add_argument("--output", default="output/v2_monthly_portfolio_review.json")
    parser.add_argument("--as-of")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    restored = restore_state_file(args.db, args.state_file)
    result = run_monthly_portfolio_review(args.db, as_of=args.as_of)
    delivery = send_messages(
        [result.message],
        enabled=args.send_telegram,
        message_thread_id=topic_id("MONTHLY"),
    )
    output = result.to_dict()
    output["state_restored"] = restored
    output["delivery"] = {"sent": delivery.sent, "message_count": delivery.message_count, "reason": delivery.reason}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    export_state_file(args.db, args.state_file)
    print(result.message)
    print(f"Telegram delivery: {delivery.reason} ({delivery.message_count} message(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
