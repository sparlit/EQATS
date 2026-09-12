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


"""
source_status.py
Shared source-status envelope for every external data fetch in the scanner.

Every function that reads from outside the process (NSE, BSE, Screener, yfinance,
bhavcopy, etc.) should return a dict that includes a "status" key from the
SOURCE_STATUSES set, so the scanner/UI can never silently treat a missing
or failed fetch as a passing signal.
"""

from typing import Any, Optional

SOURCE_STATUSES = {
    "ok",  # Source returned usable data
    "missing",  # Source is reachable, no record for this symbol/date
    "source_failed",  # Source was unreachable / returned an error
    "fallback_used",  # Primary source failed, a secondary source returned data
    "flag_only",  # Source could not confirm; scanner must flag, not auto-pass
    "not_applicable",  # This source does not apply for this symbol (e.g. corporate action for a clean stock)
}


def make_status(
    source: str,
    status: str,
    *,
    as_of: str | None = None,
    error: str | None = None,
    data: Any = None,
    **extra,
) -> dict:
    """
    Build a standardized status dict.

    `data` is the actual payload (numbers, list, dict, etc).
    `**extra` is for module-specific fields (e.g. `quarter`, `delivery_value_inr`).
    """
    if status not in SOURCE_STATUSES:
        msg = f"Unknown source status: {status!r}; expected one of {sorted(SOURCE_STATUSES)}"
        raise ValueError(msg)
    out = {
        "source": source,
        "status": status,
    }
    if as_of is not None:
        out["as_of"] = as_of
    if error is not None:
        out["error"] = error
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def worst_status(*statuses: str) -> str:
    """Return the most pessimistic of several status strings. Used to roll up
    multiple sub-source fetches into a single overall source status."""
    order = ["ok", "not_applicable", "fallback_used", "flag_only", "missing", "source_failed"]
    rank = {s: i for i, s in enumerate(order)}
    if not statuses:
        return "ok"
    return max(statuses, key=lambda s: rank.get(s, len(order)))
