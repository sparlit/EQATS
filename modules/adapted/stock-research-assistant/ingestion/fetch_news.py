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


import hashlib
import json
import os
from datetime import UTC, datetime, timezone

import feedparser
import requests

NEWS_PATH = "/Volumes/stock_research/landing/raw_landing/news"

FEEDS = {
    "moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
}


def fetch_feed(source: str, url: str):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    parsed = feedparser.parse(resp.text)
    articles = []
    for entry in parsed.entries:
        link_or_title = entry.get("link", entry.get("title", ""))
        article_id = hashlib.sha256(link_or_title.encode()).hexdigest()[:16]
        articles.append(
            {
                "article_id": article_id,
                "source": source,
                "title": entry.get("title"),
                "link": entry.get("link"),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
            }
        )
    return articles


def main():
    os.makedirs(NEWS_PATH, exist_ok=True)
    run_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")

    for source, url in FEEDS.items():
        try:
            articles = fetch_feed(source, url)
        except Exception as e:
            print(f"FAILED {source}: {e}")
            continue

        path = f"{NEWS_PATH}/{source}_{run_ts}.json"
        with open(path, "w") as f:
            json.dump(articles, f)
        print(f"wrote {len(articles)} articles -> {path}")


if __name__ == "__main__":
    main()
