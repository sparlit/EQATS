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
Safe display-formatting helpers.

Many numeric fields in the pipeline are *optional* — indicator values are ``None`` during
the warm-up window (``_safe_float`` maps NaN/inf to ``None``), so a symbol can produce a
signal while, say, ADX is still ``None``. Formatting such a value with a numeric spec
(``f"{value:.1f}"``) raises ``TypeError: unsupported format string passed to
NoneType.__format__`` and crashes the trading cycle. ``fmt_optional`` renders a placeholder
instead of raising.
"""


from typing import Any


def fmt_optional(value: Any, spec: str = "", default: str = "N/A") -> str:
    """
    Format ``value`` with ``spec``, returning ``default`` when it is ``None`` (or not
    formattable with a numeric spec).

    >>> fmt_optional(42.1234, ".1f")
    '42.1'
    >>> fmt_optional(None, ".1f")
    'N/A'
    """
    if value is None:
        return default
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return default
