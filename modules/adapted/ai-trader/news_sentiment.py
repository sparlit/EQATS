"""
News Sentiment Engine
─────────────────────
Scrapes Indian market news from RSS feeds and web sources,
computes sentiment scores, categorizes by impact level,
and stores results in TimescaleDB.

Sources:
  - MoneyControl RSS (market news, stocks, economy)
  - Economic Times RSS (markets, economy)
  - LiveMint RSS (markets)
  - NSE announcements (corporate actions, circulars)

Usage:
  from data.news_sentiment import NewsSentimentEngine
  engine = NewsSentimentEngine()
  articles = engine.fetch_all()
  engine.store(articles)
  sentiment = engine.get_market_sentiment(lookback_hours=2)
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import requests
from bs4 import BeautifulSoup

from utils.logger import get_logger

logger = get_logger("news_sentiment")

# ── RSS Feed Sources ──────────────────────────────────────────────────────────
RSS_FEEDS = {
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_economy": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    "livemint_markets": "https://www.livemint.com/rss/markets",
    "livemint_money": "https://www.livemint.com/rss/money",
}

# ── Keyword Dictionaries for Sentiment ────────────────────────────────────────

BULLISH_KEYWORDS = {
    # Strong bullish
    "rally": 2.0, "surge": 2.0, "soar": 2.0, "breakout": 1.8, "all-time high": 2.0,
    "record high": 2.0, "bull run": 2.0, "buying spree": 1.8, "strong buying": 1.8,
    # Moderate bullish
    "gains": 1.0, "rises": 1.0, "climbs": 1.0, "advances": 1.0, "upbeat": 1.0,
    "positive": 1.0, "optimistic": 1.0, "recovery": 1.0, "rebounds": 1.2,
    "outperform": 1.0, "upgrade": 1.2, "buy": 0.8, "bullish": 1.5,
    "rate cut": 1.5, "stimulus": 1.5, "easing": 1.2, "dovish": 1.5,
    "fii buying": 1.5, "dii buying": 1.2, "inflows": 1.2,
    # Mild bullish
    "steady": 0.5, "stable": 0.5, "support": 0.5, "green": 0.5,
    "higher": 0.5, "up": 0.3, "above": 0.3,
}

BEARISH_KEYWORDS = {
    # Strong bearish
    "crash": -2.0, "plunge": -2.0, "tank": -2.0, "collapse": -2.0, "bloodbath": -2.0,
    "meltdown": -2.0, "panic": -2.0, "capitulation": -2.0, "circuit breaker": -2.0,
    # Moderate bearish
    "falls": -1.0, "drops": -1.0, "declines": -1.0, "slips": -1.0, "tumbles": -1.2,
    "selloff": -1.5, "sell-off": -1.5, "correction": -1.2, "bearish": -1.5,
    "downgrade": -1.2, "sell": -0.8, "negative": -1.0, "pessimistic": -1.0,
    "rate hike": -1.5, "hawkish": -1.5, "tightening": -1.2,
    "fii selling": -1.5, "dii selling": -1.2, "outflows": -1.2,
    "recession": -1.5, "slowdown": -1.2, "inflation": -1.0,
    # Mild bearish
    "weak": -0.5, "pressure": -0.5, "resistance": -0.5, "red": -0.5,
    "lower": -0.5, "down": -0.3, "below": -0.3, "concern": -0.5, "worry": -0.5,
}

# High-impact event keywords
HIGH_IMPACT_KEYWORDS = {
    "rbi": "rbi_policy", "reserve bank": "rbi_policy", "monetary policy": "rbi_policy",
    "repo rate": "rbi_policy", "interest rate": "rbi_policy",
    "fed": "global", "federal reserve": "global", "us fed": "global",
    "fomc": "global", "powell": "global",
    "budget": "macro", "fiscal deficit": "macro", "gdp": "macro",
    "inflation": "macro", "cpi": "macro", "iip": "macro", "wpi": "macro",
    "earnings": "earnings", "quarterly results": "earnings", "q1": "earnings",
    "q2": "earnings", "q3": "earnings", "q4": "earnings", "profit": "earnings",
    "expiry": "market", "rollover": "market", "options expiry": "market",
    "nifty": "market", "sensex": "market", "bank nifty": "market",
    "war": "global", "geopolitical": "global", "crude oil": "global",
    "dollar": "global", "rupee": "global",
    "sebi": "regulatory", "circuit": "market",
}

# Symbol extraction patterns
SYMBOL_PATTERNS = {
    "NIFTY": [r"\bnifty\b", r"\bnifty\s*50\b", r"\bnse\b"],
    "BANKNIFTY": [r"\bbank\s*nifty\b", r"\bnifty\s*bank\b", r"\bbanking\s*index\b"],
    "SENSEX": [r"\bsensex\b", r"\bbse\b"],
}


@dataclass
class NewsArticle:
    """Single news article with metadata and sentiment."""
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str = ""
    symbols: List[str] = field(default_factory=list)
    category: str = "market"
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    impact_level: str = "low"
    keywords: List[str] = field(default_factory=list)


class SentimentAnalyzer:
    """Keyword-based sentiment analyzer for Indian market news."""

    def analyze(self, text: str) -> Tuple[float, str, str, List[str]]:
        """
        Analyze text and return (score, label, impact_level, keywords_found).
        Score ranges from -1.0 (very bearish) to +1.0 (very bullish).
        """
        text_lower = text.lower()
        total_score = 0.0
        keyword_count = 0
        found_keywords = []
        category = "market"

        # Check bullish keywords
        for kw, weight in BULLISH_KEYWORDS.items():
            if kw in text_lower:
                total_score += weight
                keyword_count += 1
                found_keywords.append(kw)

        # Check bearish keywords
        for kw, weight in BEARISH_KEYWORDS.items():
            if kw in text_lower:
                total_score += weight  # weight is already negative
                keyword_count += 1
                found_keywords.append(kw)

        # Check high-impact keywords
        impact = "low"
        for kw, cat in HIGH_IMPACT_KEYWORDS.items():
            if kw in text_lower:
                category = cat
                if cat in ("rbi_policy", "global"):
                    impact = "critical"
                elif cat in ("macro", "earnings"):
                    impact = "high"
                elif cat == "regulatory":
                    impact = "medium"
                else:
                    impact = max(impact, "medium", key=lambda x: ["low", "medium", "high", "critical"].index(x))

        # Normalize score to [-1, 1]
        if keyword_count > 0:
            avg_score = total_score / keyword_count
            normalized = max(-1.0, min(1.0, avg_score / 2.0))
        else:
            normalized = 0.0

        # Label
        if normalized > 0.15:
            label = "bullish"
        elif normalized < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        return normalized, label, impact, found_keywords

    def extract_symbols(self, text: str) -> List[str]:
        """Extract mentioned market symbols from text."""
        text_lower = text.lower()
        symbols = []
        for symbol, patterns in SYMBOL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    symbols.append(symbol)
                    break
        return symbols


class NewsFetcher:
    """Fetches news from RSS feeds and web sources."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        })

    def fetch_rss(self, feed_name: str, feed_url: str) -> List[Dict]:
        """Fetch and parse an RSS feed, returning list of article dicts."""
        articles = []
        try:
            resp = self.session.get(feed_url, timeout=self.timeout)
            resp.raise_for_status()

            root = ET.fromstring(resp.content)

            # Handle both RSS 2.0 and Atom feeds
            items = root.findall(".//item")
            if not items:
                # Try Atom format
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                items = root.findall(".//atom:entry", ns)

            for item in items:
                article = self._parse_rss_item(item, feed_name)
                if article:
                    articles.append(article)

            logger.info(f"Fetched {len(articles)} articles from {feed_name}")

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {feed_name}: {e}")
        except ET.ParseError as e:
            logger.warning(f"Failed to parse {feed_name} XML: {e}")

        return articles

    def _parse_rss_item(self, item: ET.Element, feed_name: str) -> Optional[Dict]:
        """Parse a single RSS item into an article dict."""
        # Extract source name from feed_name (e.g., "moneycontrol_market" -> "moneycontrol")
        source = feed_name.split("_")[0]

        title = self._get_text(item, "title")
        if not title:
            return None

        link = self._get_text(item, "link") or self._get_text(item, "guid")
        description = self._get_text(item, "description") or ""

        # Clean HTML from description
        if description:
            description = BeautifulSoup(description, "html.parser").get_text(strip=True)
            description = description[:500]  # Truncate

        # Parse publication date
        pub_date_str = self._get_text(item, "pubDate") or self._get_text(item, "published")
        published_at = self._parse_date(pub_date_str) if pub_date_str else datetime.now(timezone.utc)

        return {
            "title": title,
            "url": link,
            "source": source,
            "published_at": published_at,
            "summary": description,
        }

    @staticmethod
    def _get_text(element: ET.Element, tag: str) -> Optional[str]:
        """Get text content of a child element."""
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        # Try with namespace
        for ns_prefix in ["", "{http://www.w3.org/2005/Atom}"]:
            child = element.find(f"{ns_prefix}{tag}")
            if child is not None and child.text:
                return child.text.strip()
        return None

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse various date formats from RSS feeds."""
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
            "%a, %d %b %Y %H:%M:%S %Z",       # RFC 822 with timezone name
            "%Y-%m-%dT%H:%M:%S%z",             # ISO 8601
            "%Y-%m-%dT%H:%M:%SZ",              # ISO 8601 UTC
            "%d %b %Y %H:%M:%S %z",            # DD Mon YYYY
            "%Y-%m-%d %H:%M:%S",               # Simple datetime
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        # Fallback: try dateutil if available
        try:
            from dateutil import parser as dateutil_parser
            return dateutil_parser.parse(date_str)
        except Exception:
            return datetime.now(timezone.utc)


class NewsSentimentEngine:
    """
    Main engine: fetches news, analyzes sentiment, stores in DB.

    Usage:
        engine = NewsSentimentEngine()
        articles = engine.fetch_all()
        engine.store(articles)
        sentiment = engine.get_market_sentiment(lookback_hours=2)
    """

    def __init__(self):
        self.fetcher = NewsFetcher()
        self.analyzer = SentimentAnalyzer()

    def fetch_all(self, max_age_hours: int = 24) -> List[NewsArticle]:
        """Fetch from all RSS sources and analyze sentiment."""
        all_articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        for feed_name, feed_url in RSS_FEEDS.items():
            raw_articles = self.fetcher.fetch_rss(feed_name, feed_url)

            for raw in raw_articles:
                # Skip old articles
                pub = raw["published_at"]
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue

                # Analyze sentiment on title + summary
                text = f"{raw['title']}. {raw.get('summary', '')}"
                score, label, impact, keywords = self.analyzer.analyze(text)
                symbols = self.analyzer.extract_symbols(text)

                article = NewsArticle(
                    title=raw["title"],
                    url=raw.get("url", ""),
                    source=raw["source"],
                    published_at=pub,
                    summary=raw.get("summary", ""),
                    symbols=symbols,
                    category=impact,  # use impact category
                    sentiment_score=score,
                    sentiment_label=label,
                    impact_level=impact,
                    keywords=keywords,
                )
                all_articles.append(article)

        # Sort by published_at descending
        all_articles.sort(key=lambda a: a.published_at, reverse=True)
        logger.info(f"Total articles fetched: {len(all_articles)}")
        return all_articles

    def store(self, articles: List[NewsArticle]) -> int:
        """Store articles in the database. Returns count of new articles inserted."""
        from database.db import get_engine
        from sqlalchemy import text

        engine = get_engine()
        inserted = 0

        with engine.connect() as conn:
            for article in articles:
                try:
                    conn.execute(
                        text("""
                            INSERT INTO news_articles 
                            (published_at, source, title, url, summary, symbols, 
                             category, sentiment_score, sentiment_label, 
                             impact_level, keywords)
                            VALUES (:pub, :src, :title, :url, :summary, :symbols,
                                    :cat, :score, :label, :impact, :kw)
                            ON CONFLICT (url) DO NOTHING
                        """),
                        {
                            "pub": article.published_at,
                            "src": article.source,
                            "title": article.title,
                            "url": article.url,
                            "summary": article.summary,
                            "symbols": article.symbols,
                            "cat": article.category,
                            "score": article.sentiment_score,
                            "label": article.sentiment_label,
                            "impact": article.impact_level,
                            "kw": article.keywords,
                        },
                    )
                    inserted += 1
                except Exception as e:
                    logger.debug(f"Insert skip ({article.url[:50]}): {e}")
            conn.commit()

        logger.info(f"Stored {inserted} new articles")
        return inserted

    def get_market_sentiment(
        self,
        lookback_hours: int = 2,
        symbol: str = "NIFTY",
        as_of: Optional[datetime] = None,
    ) -> Dict:
        """
        Get aggregated market sentiment for a time window.
        
        Returns:
            {
                "score": float,          # -1.0 to +1.0
                "label": str,            # bearish / neutral / bullish
                "article_count": int,
                "bullish_count": int,
                "bearish_count": int,
                "neutral_count": int,
                "high_impact_count": int,
                "has_critical_event": bool,
                "should_block_trading": bool,
                "top_headlines": List[str],
            }
        """
        from database.db import read_sql

        ref_time = as_of or datetime.now(timezone.utc)
        cutoff = ref_time - timedelta(hours=lookback_hours)

        df = read_sql(
            """
            SELECT title, sentiment_score, sentiment_label, impact_level, symbols
            FROM news_articles
            WHERE published_at >= :cutoff AND published_at <= :ref
            ORDER BY published_at DESC
            """,
            {"cutoff": cutoff.isoformat(), "ref": ref_time.isoformat()},
        )

        if df.empty:
            return {
                "score": 0.0,
                "label": "neutral",
                "article_count": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "high_impact_count": 0,
                "has_critical_event": False,
                "should_block_trading": False,
                "top_headlines": [],
            }

        # Filter for relevant symbol if specified
        if symbol:
            # Keep articles that mention the symbol OR have no specific symbol (general market news)
            mask = df["symbols"].apply(
                lambda s: not s or symbol in s if isinstance(s, list) else True
            )
            relevant = df[mask]
            if relevant.empty:
                relevant = df  # Fallback to all if no symbol-specific news

        bullish = (relevant["sentiment_label"] == "bullish").sum()
        bearish = (relevant["sentiment_label"] == "bearish").sum()
        neutral = (relevant["sentiment_label"] == "neutral").sum()

        # Weighted average sentiment (recent articles weighted more)
        scores = relevant["sentiment_score"].values
        n = len(scores)
        if n > 0:
            # Exponential decay: most recent = weight 1.0, oldest = weight 0.5
            weights = [0.5 + 0.5 * (i / max(n - 1, 1)) for i in range(n)]
            weights.reverse()  # Most recent first in our sorted data
            avg_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        else:
            avg_score = 0.0

        avg_score = max(-1.0, min(1.0, avg_score))

        if avg_score > 0.15:
            label = "bullish"
        elif avg_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        high_impact = relevant["impact_level"].isin(["high", "critical"]).sum()
        has_critical = (relevant["impact_level"] == "critical").any()

        # Block trading if: critical event + strong bearish OR very high uncertainty
        should_block = bool(
            has_critical and (avg_score < -0.3 or high_impact >= 3)
        )

        top_headlines = relevant["title"].head(5).tolist()

        return {
            "score": round(avg_score, 4),
            "label": label,
            "article_count": len(relevant),
            "bullish_count": int(bullish),
            "bearish_count": int(bearish),
            "neutral_count": int(neutral),
            "high_impact_count": int(high_impact),
            "has_critical_event": bool(has_critical),
            "should_block_trading": should_block,
            "top_headlines": top_headlines,
        }

    def get_sentiment_features(
        self,
        timestamp: datetime,
        lookback_hours: int = 4,
    ) -> Dict[str, float]:
        """
        Get sentiment as numeric features for ML model integration.
        
        Returns dict with keys:
            news_sentiment_score:    -1 to +1
            news_article_count:      normalized 0-1
            news_bullish_ratio:      0-1
            news_bearish_ratio:      0-1
            news_high_impact:        0 or 1
            news_critical_event:     0 or 1
        """
        sentiment = self.get_market_sentiment(
            lookback_hours=lookback_hours,
            as_of=timestamp,
        )

        total = max(sentiment["article_count"], 1)
        return {
            "news_sentiment_score": sentiment["score"],
            "news_article_count": min(total / 20.0, 1.0),  # normalize to 0-1
            "news_bullish_ratio": sentiment["bullish_count"] / total,
            "news_bearish_ratio": sentiment["bearish_count"] / total,
            "news_high_impact": 1.0 if sentiment["high_impact_count"] > 0 else 0.0,
            "news_critical_event": 1.0 if sentiment["has_critical_event"] else 0.0,
        }
