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


"""
News Collector — Periodic RSS Feed Scraper
───────────────────────────────────────────
Fetches market news from RSS feeds, analyzes sentiment, and stores in DB.
Can be run as a cron job or standalone.

Usage:
  python scripts/collect_news.py                  # fetch last 24h
  python scripts/collect_news.py --hours 4        # fetch last 4h
  python scripts/collect_news.py --summary        # also print sentiment summary
  python scripts/collect_news.py --loop 300       # continuous mode, every 5min
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from data.news_sentiment import NewsSentimentEngine
from utils.logger import get_logger

logger = get_logger("collect_news")


def fetch_and_store(engine: NewsSentimentEngine, hours: int, show_summary: bool):
    """Single fetch + store + optional summary."""
    articles = engine.fetch_all(max_age_hours=hours)
    count = engine.store(articles) if articles else 0

    # Categorize
    bullish = sum(1 for a in articles if a.sentiment_label == "bullish")
    bearish = sum(1 for a in articles if a.sentiment_label == "bearish")
    neutral = len(articles) - bullish - bearish
    high_impact = sum(1 for a in articles if a.impact_level in ("high", "critical"))

    print(f"  Fetched: {len(articles)} articles | Stored: {count} new")
    print(f"  Sentiment: {bullish} bullish, {bearish} bearish, {neutral} neutral")
    print(f"  High impact: {high_impact}")

    if show_summary:
        sentiment = engine.get_market_sentiment(lookback_hours=hours)
        print(f"\n  Market Sentiment Score: {sentiment['score']:+.4f} ({sentiment['label']})")
        print(f"  Should block trading: {sentiment['should_block_trading']}")
        if sentiment["top_headlines"]:
            print("  Top headlines:")
            for h in sentiment["top_headlines"][:5]:
                print(f"    • {h[:100]}")

    return len(articles)


def main():
    parser = argparse.ArgumentParser(description="Collect market news and analyze sentiment")
    parser.add_argument("--hours", type=int, default=24, help="How far back to fetch (default: 24)")
    parser.add_argument("--summary", action="store_true", help="Print sentiment summary")
    parser.add_argument("--loop", type=int, default=0, help="Continuous mode: seconds between fetches (0=single run)")
    args = parser.parse_args()

    engine = NewsSentimentEngine()

    if args.loop > 0:
        print(f"  Continuous mode: fetching every {args.loop}s")
        while True:
            try:
                print(f"\n  [{time.strftime('%H:%M:%S')}] Fetching...")
                fetch_and_store(engine, args.hours, args.summary)
                time.sleep(args.loop)
            except KeyboardInterrupt:
                print("\n  Stopped.")
                break
            except Exception as e:
                logger.exception(f"Error: {e}")
                time.sleep(60)
    else:
        fetch_and_store(engine, args.hours, args.summary)


if __name__ == "__main__":
    main()
