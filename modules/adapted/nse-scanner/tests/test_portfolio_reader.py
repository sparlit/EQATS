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


import json
from pathlib import Path

from src.portfolio_review.portfolio_reader import build_review_queue, load_active_positions


def _write_portfolio(path: Path) -> None:
    payload = {
        "positions": {
            "tcs": {"status": "ACTIVE", "quantity": 10, "entry_price": 3500},
            "RELIANCE": {"status": "OPEN", "qty": 5, "entry_price": 2900},
            "EXITED": {"status": "CLOSED", "quantity": 4, "exit_date": "2026-07-01"},
            "ZEROQTY": {"status": "ACTIVE", "quantity": 0},
        },
        "closed": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_active_positions_filters_and_normalises(tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.json"
    _write_portfolio(portfolio)

    active = load_active_positions(portfolio)

    assert set(active) == {"RELIANCE", "TCS"}


def test_build_review_queue_is_sorted_and_periodic(tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.json"
    _write_portfolio(portfolio)

    queue = build_review_queue(portfolio, review_period="2026-08")

    assert queue["review_period"] == "2026-08"
    assert queue["count"] == 2
    assert queue["symbols"] == ["RELIANCE", "TCS"]
