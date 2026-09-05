"""
Market news feed — Indian + global financial RSS sources, fetched in parallel.

No API key needed. Parses RSS 2.0 with the stdlib (xml.etree). Each source
fails independently so one bad feed never blanks the whole panel. All
timestamps are normalized to naive UTC so sorting never mixes aware/naive.
"""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests
from loguru import logger

# (name, url, region) — free RSS feeds, markets/business focused
RSS_SOURCES = [
    # India
    ("ET Markets",       "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "india"),
    ("ET Stocks",        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "india"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets", "india"),
    ("Livemint Money",   "https://www.livemint.com/rss/money", "india"),
    ("ET Economy",       "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "india"),
    # Global
    ("CNBC",             "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "global"),
    ("CNBC Markets",     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "global"),
    ("Yahoo Finance",    "https://finance.yahoo.com/news/rssindex", "global"),
    ("MarketWatch",      "https://feeds.content.dowjones.io/public/rss/mw_topstories", "global"),
    ("BBC Business",     "https://feeds.bbci.co.uk/news/business/rss.xml", "global"),
    ("GNews Markets",    "https://news.google.com/rss/search?q=global+markets+OR+federal+reserve+OR+wall+street&hl=en-US&gl=US&ceid=US:en", "global"),
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AXIOM/1.0; +https://neura.capital)"}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_pubdate(raw: str) -> datetime | None:
    """Parse an RSS pubDate → naive UTC datetime (so all items sort together)."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, AttributeError):
            continue
    return None


def _fetch_feed(name: str, url: str, region: str, limit: int = 8) -> list[dict]:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.iter("item"):
            title = _clean(item.findtext("title", ""))
            link = (item.findtext("link", "") or "").strip()
            pub = item.findtext("pubDate", "") or ""
            if not title:
                continue
            dt = _parse_pubdate(pub)
            items.append({
                "title": title,
                "link": link,
                "source": name,
                "region": region,
                "published": dt,
                "published_str": dt.strftime("%d %b %H:%M") if dt else "",
            })
            if len(items) >= limit:
                break
        return items
    except Exception as exc:
        logger.debug("News feed failed ({}): {}", name, exc)
        return []


def fetch_market_news(max_items: int = 30) -> list[dict]:
    """
    Aggregate latest market headlines across all sources (parallel), newest first.
    Returns list of {title, link, source, region, published, published_str}.
    """
    with ThreadPoolExecutor(max_workers=len(RSS_SOURCES)) as ex:
        chunks = list(ex.map(lambda s: _fetch_feed(*s), RSS_SOURCES))
    all_items: list[dict] = [it for chunk in chunks for it in chunk]

    # Sort newest-first; items without a date sink to the bottom but stay visible
    all_items.sort(key=lambda x: x["published"] or datetime.min, reverse=True)
    # De-dup by title
    seen, deduped = set(), []
    for it in all_items:
        key = it["title"].lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    if not deduped:
        logger.warning("All news feeds returned empty")
    return deduped[:max_items]
