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


import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=site%3Areuters.com%20(Iran%20OR%20Hormuz%20OR%20%22Middle%20East%22%20OR%20%22Red%20Sea%22%20OR%20oil%20OR%20shipping%20OR%20sanctions)%20when%3A2d&hl=en-US&gl=US&ceid=US%3Aen",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.investing.com/rss/news.rss",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
]

OUTPUT_FILE = Path(__file__).resolve().parents[1] / "news_feed.json"
MAX_ARTICLES = 200


def fetch_url(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 nse-sharia-swing-assistant"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def clean_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<!\[CDATA\[|\]\]>", "", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&amp;", "&")
    value = value.replace("&quot;", '"')
    value = value.replace("&apos;", "'")
    value = value.replace("&lt;", "<")
    value = value.replace("&gt;", ">")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_tag(source: str, tag: str) -> str:
    match = re.search(
        rf"<{tag}(?: [^>]*)?>([\s\S]*?)</{tag}>",
        source,
        flags=re.IGNORECASE,
    )
    return clean_text(match.group(1)) if match else ""


def parse_rss(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = clean_text((item.findtext("title") or "").strip())
        if not title:
            continue

        description = clean_text((item.findtext("description") or "").strip())
        pub_date = clean_text((item.findtext("pubDate") or "").strip())
        link = clean_text((item.findtext("link") or "").strip())
        source = clean_text((item.findtext("source") or "").strip())

        items.append(
            {
                "title": title,
                "description": description,
                "publication_date": pub_date or datetime.now(UTC).isoformat(),
                "link": link,
                "source": source or "rss",
            }
        )

    return items


def fetch_articles() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    merged: OrderedDict[str, dict[str, str]] = OrderedDict()
    source_health: list[dict[str, object]] = []

    for url in RSS_FEEDS:
        try:
            xml_text = fetch_url(url)
            items = parse_rss(xml_text)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            source_health.append({"url": url, "status": "error", "article_count": 0})
            print(f"Feed failed: {url}: {error}", file=sys.stderr)
            continue

        status = "ok" if items else "empty"
        source_health.append({"url": url, "status": status, "article_count": len(items)})
        print(f"Feed {status}: {url}: {len(items)} article(s)")

        for item in items:
            key = (item.get("link") or item.get("title") or "").strip().lower()
            if not key:
                continue
            if key not in merged:
                merged[key] = item

    return list(merged.values()), source_health


def load_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    articles = payload.get("articles") if isinstance(payload, dict) else payload
    if not isinstance(articles, list):
        return []

    cleaned: list[dict[str, str]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        cleaned.append(
            {
                "title": title,
                "description": str(item.get("description", "")).strip(),
                "publication_date": str(item.get("publication_date", "")).strip() or datetime.now(UTC).isoformat(),
                "link": str(item.get("link", "")).strip(),
                "source": str(item.get("source", "rss")).strip() or "rss",
            }
        )

    return cleaned


def merge_articles(existing: Iterable[dict[str, str]], fresh: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    merged: OrderedDict[str, dict[str, str]] = OrderedDict()

    def add(items: Iterable[dict[str, str]]) -> None:
        for item in items:
            key = (item.get("link") or item.get("title") or "").strip().lower()
            if not key:
                continue
            merged[key] = item

    add(existing)
    add(fresh)

    articles = list(merged.values())
    articles.sort(key=lambda item: item.get("publication_date", ""), reverse=True)
    return articles[:MAX_ARTICLES]


def main() -> int:
    fresh, source_health = fetch_articles()
    existing = load_existing(OUTPUT_FILE)
    articles = merge_articles(existing, fresh)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "article_count": len(articles),
        "source_health": source_health,
        "articles": articles,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
