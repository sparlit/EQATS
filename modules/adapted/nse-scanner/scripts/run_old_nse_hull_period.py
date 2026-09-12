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


"""Send the independent Old NSE + Hull PAPER weekly or monthly topic report."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from old_nse_hull.delivery import send_message, send_period
from old_nse_hull.engine import render_period_report, render_validation_report, run_local
from old_nse_hull.multi_horizon.comparison import summarize


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("period", choices=("weekly", "monthly"))
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--shadow-state", default="old_nse_hull_shadow_state.json")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    report, summary = run_local(args.db), summarize(args.shadow_state)
    message = render_period_report(report, args.period)
    print(message)
    if args.send_telegram and not send_period(message, args.period).sent:
        return 2
    validation = render_validation_report(summary)
    print("\n" + validation)
    if args.send_telegram and not send_message(validation, "validation").sent:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
