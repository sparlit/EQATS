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


"""exchanges_listing_symbol() — local-coinlist exchange suggestions.

These suggestions power the SYMBOL_NOT_FOUND error envelope. Grounded in a
real production failure: agents retried "HYPEUSDT on BINANCE" 50+ times
because the old bare-string error offered no alternative and no retryability
signal. HYPEUSDT ships in the bundled kucoin/mexc/huobi coinlists but not in
binance's — so the suggestion set below is asserted against the real files.
"""
from tradingview_mcp.core.services.coinlist import exchanges_listing_symbol


def test_hype_suggests_real_listings_not_binance():
    listed = exchanges_listing_symbol("HYPEUSDT")
    assert "KUCOIN" in listed
    assert "MEXC" in listed
    assert "BINANCE" not in listed


def test_prefixed_symbol_matches_bare_symbol():
    assert exchanges_listing_symbol("BINANCE:HYPEUSDT") == exchanges_listing_symbol("HYPEUSDT")


def test_case_insensitive():
    assert exchanges_listing_symbol("hypeusdt") == exchanges_listing_symbol("HYPEUSDT")


def test_unknown_symbol_returns_empty():
    assert exchanges_listing_symbol("ZZZQQQ123XYZ") == []


def test_blank_symbol_returns_empty():
    assert exchanges_listing_symbol("") == []
    assert exchanges_listing_symbol("BINANCE:") == []


def test_aggregate_all_list_never_suggested():
    # all.txt contains every symbol; suggesting "ALL" as an exchange would
    # steer the model into an invalid `exchange` value.
    listed = exchanges_listing_symbol("BTCUSDT")
    assert "ALL" not in listed


def test_max_results_cap():
    listed = exchanges_listing_symbol("BTCUSDT", max_results=2)
    assert len(listed) <= 2
