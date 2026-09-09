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


"""Render the latest V2 portfolio report for a future Telegram /portfolio command."""

import argparse
import json
from pathlib import Path

from v2.portfolio_performance import PortfolioSnapshot
from v2.portfolio_store import PortfolioStore
from v2.portfolio_summary import render_portfolio_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--output", default="output/v2_portfolio/portfolio_summary.txt")
    args = parser.parse_args()
    row = PortfolioStore(args.db).latest_portfolio_snapshot()
    if row is None:
        msg = "No V2 portfolio snapshot exists yet. Run the V2 daily pipeline first."
        raise SystemExit(msg)
    snapshot = PortfolioSnapshot(**json.loads(row["snapshot_json"]))
    message = render_portfolio_summary(snapshot)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(message, encoding="utf-8")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
