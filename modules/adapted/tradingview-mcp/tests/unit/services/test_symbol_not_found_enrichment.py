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


"""SYMBOL_NOT_FOUND enrichment via TradingView symbol-search.

The chart site and the scanner are different backends: charts render fund
certificates (e.g. EGX:KASABF) that the scanner never serves, so a bare
"not found" read like a typo. When local coinlists have no suggestion, one
best-effort symbol-search lookup now explains WHAT the symbol is. The lookup
must never break the error path: any failure degrades to the old message.
"""

from unittest.mock import patch

from tradingview_mcp.core.services import screener_service as ss

KASABF_ROW = {
    "symbol": "KASABF",
    "description": "Odin Egyptian Equity Investment Fund (KASAB) Certificates",
    "type": "fund",
    "exchange": "EGX",
}


class TestParseSymbolSearch:
    def test_exact_match_preferring_requested_exchange(self):
        rows = [
            {"symbol": "KASABF", "type": "fund", "exchange": "OTC", "description": "other"},
            KASABF_ROW,
            {"symbol": "KASABF2", "type": "stock", "exchange": "EGX", "description": "near-miss"},
        ]
        info = ss._parse_symbol_search(rows, "KASABF", "EGX")
        assert info["exchange"] == "EGX"
        assert info["type"] == "fund"

    def test_no_exact_match_returns_none(self):
        rows = [{"symbol": "KASAB", "type": "stock", "exchange": "EGX"}]
        assert ss._parse_symbol_search(rows, "KASABF", "EGX") is None

    def test_garbage_rows_are_tolerated(self):
        assert ss._parse_symbol_search(["junk", None, 42], "KASABF", "EGX") is None


class TestEnvelopeEnrichment:
    def test_fund_certificate_gets_explained(self):
        with patch.object(
            ss,
            "lookup_tradingview_instrument",
            return_value={
                "symbol": "KASABF",
                "exchange": "EGX",
                "type": "fund",
                "description": KASABF_ROW["description"],
            },
        ):
            env = ss.symbol_not_found_error("KASABF", "egx")
        err = env["error"]
        assert err["code"] == "SYMBOL_NOT_FOUND"
        assert err["retryable"] is False
        assert err["instrument_type"] == "fund"
        assert "fund" in err["message"]
        assert "different backend" in err["message"]
        assert "do not retry" in err["message"]

    def test_stock_on_other_exchange_suggests_it(self):
        with (
            patch.object(
                ss,
                "lookup_tradingview_instrument",
                return_value={
                    "symbol": "XYZ",
                    "exchange": "NYSE",
                    "type": "stock",
                    "description": "XYZ Corp",
                },
            ),
            patch.object(ss, "exchanges_listing_symbol", return_value=[]),
        ):
            env = ss.symbol_not_found_error("XYZ", "egx")
        assert 'exchange="NYSE"' in env["error"]["message"]

    def test_lookup_failure_degrades_to_old_message(self):
        with (
            patch.object(ss, "lookup_tradingview_instrument", return_value=None),
            patch.object(ss, "exchanges_listing_symbol", return_value=[]),
        ):
            env = ss.symbol_not_found_error("TYPOOO", "egx")
        assert "verify the ticker" in env["error"]["message"]
        assert "instrument_type" not in env["error"]

    def test_local_suggestions_skip_the_network_lookup(self):
        """listed_on hits must keep the zero-network-cost property."""
        with (
            patch.object(ss, "exchanges_listing_symbol", return_value=["BINANCE"]),
            patch.object(
                ss, "lookup_tradingview_instrument", side_effect=AssertionError("network lookup must not fire")
            ),
        ):
            env = ss.symbol_not_found_error("BTCUSDT", "egx")
        assert "BINANCE" in env["error"]["message"]


class TestLookupCache:
    def test_only_successes_are_cached(self, monkeypatch):
        monkeypatch.setattr(ss, "_symbol_search_cache", {})
        calls = {"n": 0}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"symbols": [{"symbol": "KASABF", "type": "fund", "exchange": "EGX", "description": "d"}]}'

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "network down"
                raise OSError(msg)
            return FakeResp()

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        assert ss.lookup_tradingview_instrument("KASABF", "EGX") is None  # failure: NOT cached
        assert ss.lookup_tradingview_instrument("KASABF", "EGX")["type"] == "fund"  # retried, cached
        assert ss.lookup_tradingview_instrument("KASABF", "EGX")["type"] == "fund"  # from cache
        assert calls["n"] == 2
