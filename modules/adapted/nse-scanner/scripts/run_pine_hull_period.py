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


"""Send an isolated Pine Hull weekly or monthly paper-portfolio report."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pine_hull.engine import render_period_message
from pine_hull.telegram import send_period


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("period", choices=("weekly", "monthly"))
    parser.add_argument("--state-file", default="pine_hull_state.json")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    message = render_period_message(args.state_file, period=args.period)
    delivery = send_period(message, period=args.period, enabled=args.send_telegram)
    print(message)
    print(f"Telegram delivery: {delivery.reason} ({delivery.message_count} message(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
