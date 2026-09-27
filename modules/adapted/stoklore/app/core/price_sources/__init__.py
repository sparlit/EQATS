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


"""Pluggable OHLCV sources for "Collect max history" (see prices.collect_max_history). Each
module here implements one function:

    fetch_max(symbol) -> list[{date, open, high, low, close, volume}]  (oldest-first, ISO dates)

and raises price_sources.errors.SourceError on failure - never a bare exception, so callers can
catch exactly that type and isolate one source's failure (rate-limited, banned, endpoint changed
shape, ...) without it affecting any other source or any other symbol's collection.

If an endpoint gets blocked or its shape changes: write a new module with the same fetch_max()
signature, add one line to SOURCES below. Nothing else in the app needs to change - the API
already takes `source` as a plain string key into this dict, and the frontend already lists
`GET /api/prices/sources` to populate its selector instead of hardcoding names.
"""
from . import moneycontrol_source, yfinance_source
from .errors import SourceError

SOURCES = {
    "yfinance": yfinance_source,
    "moneycontrol": moneycontrol_source,
}

DEFAULT_SOURCE = "yfinance"


def fetch_max(source, symbol):
    """Dispatches to the named source's fetch_max(symbol). Raises ValueError for an unknown
    source name (a caller/config bug, not a runtime failure - not wrapped in SourceError) and
    SourceError for the plugin's own fetch failures."""
    if source not in SOURCES:
        msg = f"unknown price source '{source}' - available: {', '.join(SOURCES)}"
        raise ValueError(msg)
    return SOURCES[source].fetch_max(symbol)


__all__ = ["DEFAULT_SOURCE", "SOURCES", "SourceError", "fetch_max"]
