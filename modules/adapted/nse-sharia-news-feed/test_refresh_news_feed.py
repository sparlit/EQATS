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


import importlib.util
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "refresh_news_feed.py"
SPEC = importlib.util.spec_from_file_location("refresh_news_feed", SCRIPT_PATH)
assert SPEC
assert SPEC.loader
refresh_news_feed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh_news_feed)


REUTERS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>EXCLUSIVE: Iran threatens to hit Gulf states if US launches new strikes - Reuters</title>
  <description>Global escalation risk</description>
  <pubDate>Tue, 24 Mar 2026 10:00:00 GMT</pubDate>
  <link>https://news.google.com/rss/articles/reuters-fixture</link>
  <source url="https://www.reuters.com">Reuters</source>
</item></channel></rss>
"""


class RefreshNewsFeedTest(unittest.TestCase):
    def test_google_news_item_preserves_reuters_source(self) -> None:
        articles = refresh_news_feed.parse_rss(REUTERS_RSS)

        assert len(articles) == 1
        assert "Iran threatens to hit Gulf states" in articles[0]["title"]
        assert articles[0]["source"] == "Reuters"

    def test_failed_source_is_reported_without_dropping_successful_items(self) -> None:
        feeds = ["https://dead.example/rss", "https://working.example/rss"]

        def fake_fetch(url: str, timeout: int = 20) -> str:
            if "dead" in url:
                msg = "unavailable"
                raise urllib.error.URLError(msg)
            return REUTERS_RSS

        with (
            patch.object(refresh_news_feed, "RSS_FEEDS", feeds),
            patch.object(refresh_news_feed, "fetch_url", side_effect=fake_fetch),
        ):
            articles, source_health = refresh_news_feed.fetch_articles()

        assert len(articles) == 1
        assert source_health[0]["status"] == "error"
        assert source_health[1]["status"] == "ok"
        assert source_health[1]["article_count"] == 1

    def test_fresh_metadata_replaces_retained_copy(self) -> None:
        retained = [
            {
                "title": "Risk headline",
                "description": "Old metadata",
                "publication_date": "Tue, 24 Mar 2026 10:00:00 GMT",
                "link": "https://example.com/risk",
                "source": "rss",
            }
        ]
        fresh = [{**retained[0], "description": "Fresh metadata", "source": "Reuters"}]

        articles = refresh_news_feed.merge_articles(retained, fresh)

        assert articles[0]["description"] == "Fresh metadata"
        assert articles[0]["source"] == "Reuters"


if __name__ == "__main__":
    unittest.main()
