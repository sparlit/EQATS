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


"""
market/source_tracker.py
────────────────────────
Tracks which data source served each request and emits fallback warnings.

Usage:
    from market.source_tracker import record_source, get_last_source, warn_fallback

    record_source("options", "nse_scraper")
    get_last_source("options")          # → "nse_scraper"
    warn_fallback("options", "token expired", "nse_scraper")
"""


_last_source: dict[str, str] = {}


def record_source(data_type: str, source: str) -> None:
    """Record which source served the most recent request for data_type."""
    _last_source[data_type] = source


def get_last_source(data_type: str) -> str:
    """
    Return the source that served the most recent request for data_type.
    Returns "none" if no request has been recorded yet.
    """
    return _last_source.get(data_type, "none")


def warn_fallback(data_type: str, reason: str, source: str) -> None:
    """
    Print a visible warning when the primary source failed and a fallback is used.

    Args:
        data_type: Human-readable label ("options", "quotes", "holdings", etc.)
        reason:    Why the primary failed (exception message or short description)
        source:    The fallback source being used ("nse_scraper", "yfinance", etc.)
    """
    try:
        from rich.console import Console

        _console = Console(stderr=True)
        _console.print(
            f"  [yellow]⚠[/yellow] {data_type}: primary failed ({reason[:80]}) "
            f"— using [dim]{source}[/dim] (may be delayed)"
        )
    except Exception:
        # Rich not available — plain print
        print(f"⚠ {data_type}: primary failed ({reason[:80]}) — using {source}")
