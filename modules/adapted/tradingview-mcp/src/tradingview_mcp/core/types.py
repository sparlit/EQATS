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
Shared type definitions and primitive helpers for the TradingView MCP package.

Keeping these in one place avoids circular imports between service modules
and lets server.py import cleanly without depending on any service.
"""

from typing import Any, Dict, Optional

from typing_extensions import TypedDict

# ── Indicator containers ───────────────────────────────────────────────────────


class IndicatorMap(TypedDict, total=False):
    open: float | None
    close: float | None
    SMA20: float | None
    BB_upper: float | None
    BB_lower: float | None
    EMA50: float | None
    RSI: float | None
    volume: float | None


class Row(TypedDict):
    symbol: str
    changePercent: float
    indicators: IndicatorMap


class MultiRow(TypedDict):
    symbol: str
    changes: dict[str, float | None]
    base_indicators: IndicatorMap


# ── Primitive helpers ──────────────────────────────────────────────────────────


def map_indicators(raw: dict[str, Any]) -> IndicatorMap:
    """Map a raw TradingView indicators dict to the typed IndicatorMap subset."""
    return IndicatorMap(
        open=raw.get("open"),
        close=raw.get("close"),
        SMA20=raw.get("SMA20"),
        BB_upper=raw.get("BB.upper") if "BB.upper" in raw else raw.get("BB_upper"),
        BB_lower=raw.get("BB.lower") if "BB.lower" in raw else raw.get("BB_lower"),
        EMA50=raw.get("EMA50"),
        RSI=raw.get("RSI"),
        volume=raw.get("volume"),
    )


def percent_change(o: float | None, c: float | None) -> float | None:
    """Safe percentage change calculation: (close - open) / open * 100."""
    try:
        if o in (None, 0) or c is None:
            return None
        return (c - o) / o * 100
    except Exception:
        return None


def tf_to_tv_resolution(tf: str | None) -> str | None:
    """Map human-readable timeframe strings to TradingView resolution codes."""
    if not tf:
        return None
    return {
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1D": "1D",
        "1W": "1W",
        "1M": "1M",
    }.get(tf)


def safe_round(value: Any, decimals: int = 4) -> float | None:
    """Round a value safely, returning None if the value is None or invalid."""
    if value is None:
        return None
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None
