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


"""Durable run-state manifest used for partial failure recovery."""

import json
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any


def write_recovery_manifest(
    results: list[dict[str, Any]],
    *,
    review_period: str,
    path: str | Path = "data/portfolio_review_recovery.json",
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    failed = [item for item in results if item.get("status") == "FAILED"]
    skipped = [item for item in results if item.get("status") == "SKIPPED"]
    payload = {
        "review_period": review_period,
        "generated_at": datetime.now(UTC).isoformat(),
        "failed_symbols": [item.get("symbol", "") for item in failed],
        "skipped_symbols": [item.get("symbol", "") for item in skipped],
        "retry_required": bool(failed),
        "results": results,
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination
