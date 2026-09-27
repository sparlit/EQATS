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


"""Self-check for the watchlist event scan: all 4 event types insert once, re-scan inserts zero."""
import sys
from pathlib import Path

# Run as a script, so the repo root has to go on sys.path before importing app.* - the package
# is not installed, it just sits at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import UTC, datetime, timezone

from app.core import db, events, scraper, sentiment

SYMBOL = "ZZZEVENTTEST"


def _stub(monkeypatch=None):
    """Stubs network scrapers and the sentiment model with canned data (no downloads, no HTTP)."""
    scraper.get_news = lambda symbol: [
        {
            "title": "Test headline",
            "summary": "Test summary",
            "url": "https://example.com/a1",
            "published_at": datetime.now(UTC),
        }
    ]
    scraper.get_quote = lambda symbol: {
        "regularMarketChangePercent": 7.5,  # above movement's 5% threshold
        "regularMarketVolume": 5000,
        "averageVolume": 1000,  # above volume's 2x threshold
    }
    scraper.get_corporate_actions = lambda symbol, since_days=30: [
        {"action_type": "dividend", "date": "2026-07-15", "detail": "Dividend of ₹12 per share"},
    ]
    sentiment.analyze = lambda text: {"label": "positive", "score": 0.99}


def test_scan_symbol_inserts_then_dedups():
    db.init_schema()
    _stub()
    try:
        assert events.scan_symbol(SYMBOL) == 4  # news + price_move + volume_spike + corporate_action
        assert events.scan_symbol(SYMBOL) == 0  # identical re-scan: every dedup key already exists
        types = {e["event_type"] for e in db.list_events(symbol=SYMBOL)}
        assert types == {"news", "price_move", "volume_spike", "corporate_action"}
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM stock_events WHERE symbol = %s", (SYMBOL,))


def test_should_auto_scan_once_per_day():
    assert events.should_auto_scan(None, "2026-07-31") is True  # never run
    assert events.should_auto_scan("2026-07-30", "2026-07-31") is True  # new day
    assert events.should_auto_scan("2026-07-31", "2026-07-31") is False  # already ran today


if __name__ == "__main__":
    test_scan_symbol_inserts_then_dedups()
    test_should_auto_scan_once_per_day()
    print("all checks passed")
