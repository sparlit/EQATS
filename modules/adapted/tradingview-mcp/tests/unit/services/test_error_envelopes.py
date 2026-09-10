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


"""Error-envelope contract for the hot single-symbol analysis paths.

Asserts the structured-error rules the MCP guidance calls for:
- SYMBOL_NOT_FOUND: retryable=False + actionable `listed_on` suggestions
  (a valid-but-unlisted symbol must NOT be retried on the same exchange).
- UPSTREAM_ERROR (transient TradingView outage): retryable=True with an
  explicit retry_after_s, so agents wait-and-retry instead of hammering.
- Message prefixes stay backward-compatible ("No data found for",
  "Analysis failed:") for anyone substring-matching the old strings.
"""
import pytest
from tradingview_mcp.core.errors import is_error
from tradingview_mcp.core.services import scanner_service, screener_service


class _NoIndicators:
    """Truthy analysis row lacking the `indicators` attribute."""


def test_analyze_coin_symbol_not_found_envelope(monkeypatch):
    monkeypatch.setattr(screener_service, "get_multiple_analysis", lambda **kwargs: {})
    monkeypatch.setattr(screener_service, "_TA_AVAILABLE", True)

    out = screener_service.analyze_coin("HYPEUSDT", "BINANCE", "1h")

    assert is_error(out)
    err = out["error"]
    assert err["code"] == "SYMBOL_NOT_FOUND"
    assert err["retryable"] is False
    assert err["message"].startswith("No data found for HYPEUSDT on BINANCE")
    assert "KUCOIN" in err["listed_on"]
    assert "BINANCE" not in err["listed_on"]
    assert err["symbol"] == "HYPEUSDT"
    assert err["timeframe"] == "1h"


def test_analyze_coin_unknown_ticker_says_verify_spelling(monkeypatch):
    monkeypatch.setattr(screener_service, "get_multiple_analysis", lambda **kwargs: {})
    monkeypatch.setattr(screener_service, "_TA_AVAILABLE", True)

    out = screener_service.analyze_coin("ZZZQQQ123XYZ", "BINANCE", "1h")

    err = out["error"]
    assert err["code"] == "SYMBOL_NOT_FOUND"
    assert err["retryable"] is False
    assert err["listed_on"] == []
    assert "verify the ticker" in err["message"].lower()


def test_analyze_coin_upstream_outage_is_retryable(monkeypatch):
    def boom(**kwargs):
        msg = (
            "Upstream TradingView scanner returned transient errors on all 3 "
            "attempts spanning 5s (JSONDecodeError('Expecting value: line 1 "
            "column 1 (char 0)'))."
        )
        raise RuntimeError(msg)

    monkeypatch.setattr(screener_service, "get_multiple_analysis", boom)
    monkeypatch.setattr(screener_service, "_TA_AVAILABLE", True)

    out = screener_service.analyze_coin("BTCUSDT", "BINANCE", "1h")

    assert is_error(out)
    err = out["error"]
    assert err["code"] == "UPSTREAM_ERROR"
    assert err["retryable"] is True
    assert err["retry_after_s"] == 60
    assert err["message"].startswith("Analysis failed:")


def test_volume_confirmation_symbol_not_found_envelope(monkeypatch):
    monkeypatch.setattr(scanner_service, "get_multiple_analysis", lambda **kwargs: {})

    out = scanner_service.volume_confirmation_analyze("HYPEUSDT", "BINANCE", "15m")

    err = out["error"]
    assert err["code"] == "SYMBOL_NOT_FOUND"
    assert err["retryable"] is False
    assert "KUCOIN" in err["listed_on"]
    assert err["full_symbol"] == "BINANCE:HYPEUSDT"


def test_volume_confirmation_no_indicator_row_not_retryable(monkeypatch):
    row = _NoIndicators()
    monkeypatch.setattr(
        scanner_service,
        "get_multiple_analysis",
        lambda **kwargs: {"BINANCE:BTCUSDT": row},
    )

    out = scanner_service.volume_confirmation_analyze("BTCUSDT", "BINANCE", "15m")

    err = out["error"]
    assert err["code"] == "NO_DATA"
    assert err["retryable"] is False
    assert err["message"].startswith("No indicator data for BINANCE:BTCUSDT")


def test_volume_confirmation_upstream_outage_is_retryable(monkeypatch):
    def boom(**kwargs):
        msg = "Upstream TradingView scanner returned transient errors on all 3 attempts spanning 4s."
        raise RuntimeError(msg)

    monkeypatch.setattr(scanner_service, "get_multiple_analysis", boom)

    out = scanner_service.volume_confirmation_analyze("BTCUSDT", "BINANCE", "15m")

    err = out["error"]
    assert err["code"] == "UPSTREAM_ERROR"
    assert err["retryable"] is True
    assert err["retry_after_s"] == 60
