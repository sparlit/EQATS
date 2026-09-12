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


"""Build portfolio_health.json and optionally print Telegram Message 3."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.portfolio_review.health_builder import build_portfolio_health, save_portfolio_health
from src.portfolio_review.telegram_health import render_portfolio_health_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build consolidated portfolio health output")
    parser.add_argument("--portfolio", default="portfolio.json")
    parser.add_argument("--reports-root", default="reports/portfolio")
    parser.add_argument("--output", default="data/portfolio_health.json")
    parser.add_argument("--telegram-output", default="data/portfolio_health_message.txt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    health = build_portfolio_health(args.portfolio, args.reports_root)
    output = save_portfolio_health(health, args.output)
    message = render_portfolio_health_message(health)
    message_path = Path(args.telegram_output)
    message_path.parent.mkdir(parents=True, exist_ok=True)
    message_path.write_text(message + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "health_output": str(output),
                "telegram_output": str(message_path),
                "position_count": health["position_count"],
                "reviewed_count": health["reviewed_count"],
                "pending_count": health["pending_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
