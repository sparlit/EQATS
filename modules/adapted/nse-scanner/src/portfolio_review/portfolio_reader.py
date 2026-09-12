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


"""Read the existing portfolio.json and create a monthly review queue."""


import json
from datetime import date
from pathlib import Path
from typing import Any

from .models import ReviewQueueItem


def _normalise_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _is_active(position: dict[str, Any]) -> bool:
    """Return True for an open position that should receive a review.

    The current repository stores active positions inside the ``positions``
    mapping. These defensive checks also support future status/quantity fields.
    """
    status = str(position.get("status", "ACTIVE")).strip().upper()
    exit_date = position.get("exit_date")
    quantity = position.get("quantity", position.get("qty", 1))

    try:
        quantity_is_positive = float(quantity) > 0
    except (TypeError, ValueError):
        quantity_is_positive = True  # legacy positions may not store quantity

    return status in {"ACTIVE", "OPEN"} and not exit_date and quantity_is_positive


def load_active_positions(portfolio_path: str | Path = "portfolio.json") -> dict[str, dict[str, Any]]:
    path = Path(portfolio_path)
    if not path.exists():
        msg = f"Portfolio file not found: {path}"
        raise FileNotFoundError(msg)

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    positions = payload.get("positions", {})
    if not isinstance(positions, dict):
        msg = "portfolio.json field 'positions' must be an object"
        raise ValueError(msg)

    active: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_position in positions.items():
        symbol = _normalise_symbol(raw_symbol)
        if not symbol or not isinstance(raw_position, dict) or not _is_active(raw_position):
            continue
        active[symbol] = dict(raw_position)

    return active


def build_review_queue(
    portfolio_path: str | Path = "portfolio.json",
    review_period: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, symbol-level queue for the monthly review job."""
    period = review_period or date.today().strftime("%Y-%m")
    active = load_active_positions(portfolio_path)
    items = [ReviewQueueItem(symbol=symbol, position=active[symbol]).to_dict() for symbol in sorted(active)]

    return {
        "review_period": period,
        "count": len(items),
        "symbols": [item["symbol"] for item in items],
        "items": items,
    }
