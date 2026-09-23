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


"""Regression test: fetch_multi_timeframe_patterns must query the CALLER'S
symbols, not the first N arbitrary rows of a whole-exchange scan.

The old code did ``set_markets(...).limit(len(symbols))`` — the ``symbols``
argument was silently ignored while the resilience cache was keyed on it, so
different symbol lists collided onto the same wrong rows.
"""

from unittest.mock import patch

import pandas as pd
from tradingview_mcp.core.services import screener_service


def test_query_targets_the_requested_symbols():
    captured = {}

    def fake_scan(q, cache_key=None, **_):
        captured["query"] = q.query
        return 0, pd.DataFrame()

    with patch.object(screener_service, "_scan_with_retry", side_effect=fake_scan):
        screener_service.fetch_multi_timeframe_patterns(
            "kucoin",
            ["KUCOIN:AUSDT", "BUSDT"],
            "15m",
            3,
            10.0,
        )

    tickers = captured["query"]["symbols"]["tickers"]
    # Prefixed symbols pass through; bare ones get the exchange prefix.
    assert tickers == ["KUCOIN:AUSDT", "KUCOIN:BUSDT"]
