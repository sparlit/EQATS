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


"""Strict input validation at the MCP tool boundary.

sanitize_exchange/timeframe silently substituted the default on bad input —
an LLM asking for KRAKEN got KUCOIN data with no indication anything was
wrong. Tools now return INVALID_EXCHANGE / INVALID_TIMEFRAME envelopes that
list valid values, so callers can self-correct. Aliases ("1d" → "1D") and
omitted parameters still resolve silently.
"""

import asyncio

import pytest
from tradingview_mcp import server
from tradingview_mcp.core.errors import ScreenerServiceError
from tradingview_mcp.core.utils.validators import validate_exchange, validate_timeframe


class TestValidators:
    def test_valid_and_aliased_inputs_pass(self):
        assert validate_exchange("BINANCE", "kucoin") == "binance"
        assert validate_exchange("", "kucoin") == "kucoin"
        assert validate_timeframe("1d", "5m") == "1D"
        assert validate_timeframe(" 4H ", "5m") == "4h"
        assert validate_timeframe("", "15m") == "15m"

    def test_unknown_exchange_raises_with_valid_list(self):
        with pytest.raises(ScreenerServiceError) as exc_info:
            validate_exchange("KRAKEN", "kucoin")
        env = exc_info.value.to_envelope()
        assert env["error"]["code"] == "INVALID_EXCHANGE"
        assert "binance" in env["error"]["valid_exchanges"]
        assert env["error"]["retryable"] is False

    def test_unknown_timeframe_raises_with_valid_list(self):
        with pytest.raises(ScreenerServiceError) as exc_info:
            validate_timeframe("30m", "15m")
        env = exc_info.value.to_envelope()
        assert env["error"]["code"] == "INVALID_TIMEFRAME"
        assert "1D" in env["error"]["valid_timeframes"]


class TestToolBoundary:
    def test_top_gainers_returns_invalid_exchange_envelope(self):
        result = asyncio.run(server.top_gainers(exchange="KRAKEN"))
        assert result["error"]["code"] == "INVALID_EXCHANGE"

    def test_coin_analysis_returns_invalid_timeframe_envelope(self):
        result = server.coin_analysis("BTCUSDT", exchange="KUCOIN", timeframe="30m")
        assert result["error"]["code"] == "INVALID_TIMEFRAME"

    def test_egx_tool_returns_invalid_timeframe_envelope(self):
        result = server.egx_market_overview(timeframe="2h")
        assert result["error"]["code"] == "INVALID_TIMEFRAME"

    def test_combined_analysis_rejects_bad_exchange(self):
        result = asyncio.run(server.combined_analysis("AAPL", exchange="NOPE"))
        assert result["error"]["code"] == "INVALID_EXCHANGE"


class TestCombinedAnalysisLegFailure:
    def test_one_failing_leg_degrades_not_crashes(self, monkeypatch):
        def ok_tech(symbol, exchange, timeframe):
            return {"market_sentiment": {"momentum": "Bullish", "buy_sell_signal": "BUY"}}

        def boom_sentiment(symbol, category):
            msg = "marketaux down"
            raise RuntimeError(msg)

        def ok_news(symbol, category, limit):
            return {"count": 1, "items": [{"title": "x"}]}

        monkeypatch.setattr(server, "analyze_coin", ok_tech)
        monkeypatch.setattr(server, "analyze_sentiment", boom_sentiment)
        monkeypatch.setattr(server, "fetch_news_summary", ok_news)

        result = asyncio.run(server.combined_analysis("AAPL", exchange="NASDAQ"))

        # Whole-tool result survives; only the failed leg carries an envelope.
        assert result["technical"]["market_sentiment"]["momentum"] == "Bullish"
        assert result["sentiment"]["error"]["code"] == "INTERNAL_ERROR"
        assert result["news"]["count"] == 1


class TestFuturesDirectionValidation:
    def test_typo_direction_errors_instead_of_returning_losers(self):
        from tradingview_mcp.core.services.futures_service import get_futures_movers

        result = get_futures_movers(direction="gainer")
        assert "error" in result
        assert "gainers" in result["error"]
