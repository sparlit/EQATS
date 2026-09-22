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


"""Regression test for multi-timeframe alignment score misattribution.

``alignment_scores`` was appended only for timeframes that succeeded, but
``scores_by_tf`` zipped it against the FULL timeframe list — so when 1W
errored, 1D's score was reported under the "1W" key and every later
timeframe shifted by one. Scores are now recorded as (tf, score) pairs.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tradingview_mcp.core.services import screener_service


def _bullish_indicators() -> dict[str, Any]:
    return {
        "open": 100.0,
        "close": 110.0,
        "high": 111.0,
        "low": 99.0,
        "SMA20": 105.0,
        "BB.upper": 115.0,
        "BB.lower": 95.0,
        "EMA20": 105.0,
        "EMA50": 104.0,
        "EMA100": 103.0,
        "EMA200": 100.0,
        "RSI": 55.0,
        "MACD.macd": 1.0,
        "MACD.signal": 0.5,
        "ADX": 30.0,
        "volume": 1_000.0,
        "volume.SMA20": 800.0,
        "VWAP": 105.0,
        "ATR": 2.0,
    }


def test_failed_timeframe_does_not_shift_scores(monkeypatch):
    monkeypatch.setattr(screener_service, "_TA_AVAILABLE", True)

    def fake_analysis(screener, interval, symbols):
        if interval == "1W":
            msg = "upstream 500 for weekly"
            raise RuntimeError(msg)
        return {symbols[0]: SimpleNamespace(indicators=_bullish_indicators())}

    with patch.object(screener_service, "get_multiple_analysis", side_effect=fake_analysis):
        result = screener_service.run_multi_timeframe_analysis(
            "KUCOIN:BTCUSDT",
            "kucoin",
        )

    scores = result["alignment"]["scores_by_tf"]

    # The failed timeframe must be absent — before the fix it received the
    # next timeframe's score and every subsequent key shifted by one.
    assert "1W" not in scores
    assert set(scores) == {"1D", "4h", "1h", "15m"}
    assert "error" in result["timeframes"]["1W"]

    # Every reported score must agree with that SAME timeframe's bias.
    bias_to_score = {"Bullish": 1, "Bearish": -1, "Neutral": 0}
    for tf, score in scores.items():
        assert score == bias_to_score[result["timeframes"][tf]["bias"]], tf
