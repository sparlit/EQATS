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


"""Run the isolated progressive penny/microcap PAPER scanner."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nse_loader import init_database
from nse_market_store import restore_prices
from penny_microcap.config import PennyConfig
from penny_microcap.engine import scan_market
from penny_microcap.telegram import render_topic_messages, send_messages
from portfolio_accounting.config import rollout_directory
from v2.database import V2Database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--date")
    parser.add_argument("--output", default="output/penny_microcap/daily.json")
    parser.add_argument("--restore-snapshots", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    parser.add_argument(
        "--ladder-inspired", action="store_true", help="Experimental Penny EMA14/21 scoring and recent crossover gate"
    )
    parser.add_argument(
        "--activate-penny-profile",
        action="store_true",
        help="Use a separate forward PAPER ledger and allow scheduled delivery of the EMA14/21 profile",
    )
    parser.add_argument(
        "--uniform-portfolio-dir",
        default=rollout_directory(),
        help="Opt-in PAPER accounting directory; persist this directory between sessions",
    )
    args = parser.parse_args()
    if args.activate_penny_profile and not args.ladder_inspired:
        parser.error("--activate-penny-profile requires --ladder-inspired")
    if args.ladder_inspired and not args.activate_penny_profile and (args.send_telegram or args.uniform_portfolio_dir):
        parser.error(
            "Research profile requires --uniform-portfolio-dir '' and no --send-telegram; keep a separate forward cohort before activation"
        )
    if args.activate_penny_profile:
        args.uniform_portfolio_dir = args.uniform_portfolio_dir or "paper_portfolios"
    if args.restore_snapshots:
        init_database(args.db)
        print("Restored snapshots:", restore_prices(args.db, min_days=1))
    database = V2Database(args.db)
    prices = database.load_prices(args.date)
    if prices.empty:
        msg = "No market prices available"
        raise RuntimeError(msg)
    as_of = str(pd.to_datetime(prices["trade_date"]).max().date()) if args.date is None else args.date
    master = database.load_symbol_master(as_of)
    restricted = database.load_restricted_symbols(as_of)
    lifecycle_registry = database.load_lifecycle_registry()
    report = scan_market(
        prices,
        symbol_master=master,
        restricted=restricted,
        lifecycle_registry=lifecycle_registry,
        config=PennyConfig(ladder_inspired=args.ladder_inspired),
    )
    if args.uniform_portfolio_dir:
        from portfolio_accounting.service import update_portfolio, write_reports

        ledger_name = "penny_ema14_21.sqlite" if args.activate_penny_profile else "penny.sqlite"
        snapshot = update_portfolio(
            "Penny",
            report,
            database,
            Path(args.uniform_portfolio_dir) / ledger_name,
            provenance="PENNY_EMA14_21_FORWARD_20260923" if args.activate_penny_profile else "FORWARD_PAPER_COHORT",
        )
        report["uniform_portfolio"] = snapshot
        report["portfolio"] = [p for p in snapshot["positions"] if p["remaining_quantity"]]
        write_reports(snapshot, args.uniform_portfolio_dir)
    topic_order = ("early_radar", "confirming", "ready", "circuit_risk", "portfolio", "system")
    messages = {topic: render_topic_messages(report, topic) for topic in topic_order}
    deliveries = {
        topic: send_messages(messages[topic], topic, enabled=args.send_telegram).__dict__ for topic in topic_order
    }
    payload = {**report, "delivery": deliveries}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\n\n".join(message for topic in topic_order for message in messages[topic]))
    failed = []
    for topic in topic_order:
        result = deliveries[topic]
        status = "SENT" if result["sent"] else ("SKIPPED" if result["reason"] == "disabled" else "FAILED")
        print(f"[TELEGRAM] {topic}: {status} ({result['reason']}; pages={len(messages[topic])})")
        if args.send_telegram and not result["sent"]:
            failed.append(topic)
    if failed:
        print(f"::warning::Penny Telegram delivery incomplete for: {', '.join(failed)}")
    # Preserve the generated report and successful routes when one topic is
    # misconfigured. Fail only when the Telegram bot delivered nothing at all.
    sent_count = sum(1 for result in deliveries.values() if result["sent"])
    return 2 if args.send_telegram and sent_count == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
