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


"""Versioned JSON persistence for validated portfolio reviews."""


import json
from pathlib import Path
from typing import Any

from .review_validator import assert_valid_review


class ReviewAlreadyExistsError(FileExistsError):
    """Raised when an immutable monthly review already exists."""


def save_review(
    review: dict[str, Any],
    reports_root: str | Path = "reports/portfolio",
    overwrite: bool = False,
) -> tuple[Path, Path]:
    symbol = str(review.get("symbol", "")).strip().upper()
    assert_valid_review(review, expected_symbol=symbol)

    symbol_dir = Path(reports_root) / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    dated_path = symbol_dir / f"{review['review_period']}.json"
    latest_path = symbol_dir / "latest.json"

    if dated_path.exists() and not overwrite:
        msg = f"Monthly review already exists: {dated_path}"
        raise ReviewAlreadyExistsError(msg)

    encoded = json.dumps(review, indent=2, ensure_ascii=False, default=str) + "\n"
    dated_path.write_text(encoded, encoding="utf-8")
    latest_path.write_text(encoded, encoding="utf-8")
    return dated_path, latest_path


def load_latest_review(symbol: str, reports_root: str | Path = "reports/portfolio") -> dict[str, Any] | None:
    path = Path(reports_root) / symbol.strip().upper() / "latest.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
