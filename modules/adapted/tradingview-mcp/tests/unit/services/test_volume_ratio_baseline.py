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


"""Regression tests for the volume-ratio baseline fallback bug.

When a symbol had no ``volume.SMA20`` column, ``volume_breakout_scan`` used
``volume / (volume / 2)`` as its ratio — mathematically always exactly 2.0.
With the default ``volume_multiplier=2.0`` gate that meant every baseline-less
symbol "passed" on price change alone, flooding the scan with breakouts that
carried no volume signal. Symbols without a baseline must be skipped instead.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tradingview_mcp.core.services import scanner_service


def _indicators(sma20_volume: Any) -> dict[str, Any]:
    """A +10% bar (clears price_change_min=3.0) with a configurable baseline."""
    return {
        "volume": 10_000.0,
        "close": 110.0,
        "open": 100.0,
        "volume.SMA20": sma20_volume,
        "RSI": 55.0,
        "BB.upper": 115.0,
        "BB.lower": 95.0,
    }


def _scan(analysis: dict) -> list[dict]:
    with (
        patch.object(scanner_service, "get_multiple_analysis", return_value=analysis),
        patch.object(scanner_service, "load_symbols", return_value=list(analysis)),
    ):
        return scanner_service.volume_breakout_scan("KUCOIN", "15m")


def test_symbol_without_volume_baseline_is_skipped():
    """No volume.SMA20 → no volume signal → must not appear as a breakout."""
    analysis = {
        "NOBASE": SimpleNamespace(indicators=_indicators(sma20_volume=None)),
        "ZEROBASE": SimpleNamespace(indicators=_indicators(sma20_volume=0.0)),
    }
    assert _scan(analysis) == []


def test_symbol_with_real_volume_spike_still_detected():
    analysis = {
        "REAL": SimpleNamespace(indicators=_indicators(sma20_volume=1_000.0)),
        "QUIET": SimpleNamespace(indicators=_indicators(sma20_volume=9_000.0)),
    }
    rows = _scan(analysis)
    assert [r["symbol"] for r in rows] == ["REAL"]
    assert rows[0]["volume_ratio"] == 10.0
