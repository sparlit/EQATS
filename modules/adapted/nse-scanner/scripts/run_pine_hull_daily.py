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


"""Run the isolated Pine Hull EOD paper-trading system."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nse_loader import init_database
from nse_market_store import restore_prices
from pine_hull.engine import PineConfig, render_portfolio_message, run_daily
from pine_hull.preview import render_daily_signals
from pine_hull.telegram import send_portfolio, send_signals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--state-file", default="pine_hull_state.json")
    parser.add_argument("--output", default="output/pine_hull_daily_run.json")
    parser.add_argument("--date")
    parser.add_argument("--capital", type=float, default=300_000.0)
    parser.add_argument("--restore-snapshots", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    if args.restore_snapshots:
        init_database(args.db)
        print("Restored snapshots:", restore_prices(args.db, min_days=1))
    result = run_daily(
        args.db, state_path=args.state_file, as_of=args.date, config=PineConfig(capital_base=args.capital)
    )
    signals, portfolio = render_daily_signals(result), render_portfolio_message(result)
    signals_delivery = send_signals([signals], enabled=args.send_telegram)
    portfolio_delivery = send_portfolio(portfolio, enabled=args.send_telegram)
    payload = {**result, "delivery": {"signals": signals_delivery.__dict__, "portfolio": portfolio_delivery.__dict__}}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(signals)
    print("\n" + portfolio)
    deliveries = {"daily": signals_delivery, "portfolio": portfolio_delivery}
    for topic, delivery in deliveries.items():
        status = "SENT" if delivery.sent else ("SKIPPED" if not args.send_telegram else "FAILED")
        print(f"[TELEGRAM] {topic}: {status} ({delivery.reason}; messages={delivery.message_count})")
    failed = [topic for topic, result in deliveries.items() if args.send_telegram and not result.sent]
    if failed:
        print(f"::warning::Hull Telegram delivery incomplete for: {', '.join(failed)}")
    return 2 if args.send_telegram and len(failed) == len(deliveries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
