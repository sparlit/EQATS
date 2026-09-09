from __future__ import annotations

import datetime
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timezone
from xml.etree import ElementTree as ET

import pytz
import requests

logger = logging.getLogger(__name__)


def is_ist_market_session_active(dt: datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.now(ist)
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


"""
Market news feed — Indian + global financial RSS sources, fetched in parallel.

No API key needed. Parses RSS 2.0 with the stdlib (xml.etree). Each source
fails independently so one bad feed never blanks the whole panel. All
timestamps are normalized to naive UTC so sorting never mixes aware/naive.
"""

# (name, url, region) — free RSS feeds, markets/business focused
RSS_SOURCES = [
    # India
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "india"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "india"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets", "india"),
    ("Livemint Money", "https://www.livemint.com/rss/money", "india"),
    ("ET Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "india"),
    # Global
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "global"),
    ("CNBC Markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "global"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "global"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "global"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "global"),
    (
        "GNews Markets",
        "https://news.google.com/rss/search?q=global+markets+OR+federal+reserve+OR+wall+street&hl=en-US&gl=US&ceid=US:en",
        "global",
    ),
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AXIOM/1.0; +https://neura.capital)"}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_pubdate(raw: str) -> datetime | None:
    """Parse an RSS pubDate → naive UTC datetime (so all items sort together."""
    if not raw:
        return None
    # Try common RSS date formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(UTC).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    logger.warning("Failed to parse pubDate: %s", raw)
    return None
