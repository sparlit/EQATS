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


"""Shared live price helper for all web routes.

Provides a single function to fetch live prices for any list of symbols,
with error handling and fallback. Used by every route that displays stock prices.
"""


import logging
from typing import Any

log = logging.getLogger(__name__)


def fetch_live_prices(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch live prices for a list of symbols. Returns {} on failure.

    Returns {SYMBOL: {last_price, open, high, low, close, volume, net_change, ...}}
    """
    if not symbols:
        return {}
    try:
        from indian_quant.web.live_prices import LivePriceService

        lps = LivePriceService()
        return lps.get_live_prices(list(set(symbols)))
    except Exception as e:
        log.warning("Live prices fetch failed for %d symbols: %s", len(symbols), e)
        return {}


def get_live_price_map(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices, return simple {SYMBOL: last_price} map."""
    raw = fetch_live_prices(symbols)
    return {sym: data.get("last_price", 0) for sym, data in raw.items() if data.get("last_price")}
