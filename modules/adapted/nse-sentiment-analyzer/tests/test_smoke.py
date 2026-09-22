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


"""Smoke tests for import regressions and core module wiring."""

import aggregate_sentiment
import data_fetcher
import sentiment
from sentiment import get_sia

import indicators


def test_module_paths_not_empty():
    assert hasattr(data_fetcher, "get_stock_info")
    assert hasattr(data_fetcher, "resolve_ticker")
    assert hasattr(data_fetcher, "search_news")
    assert hasattr(sentiment, "get_sia")
    assert hasattr(sentiment, "analyze_headline_sentiment")
    assert hasattr(indicators, "get_technical_indicators")
    assert hasattr(aggregate_sentiment, "compute_smartscore")


def test_vader_lexicon_loaded():
    sia = get_sia()
    assert "bullish" in sia.lexicon
    assert "bearish" in sia.lexicon
    assert sia.lexicon["growth"] == 1.0
