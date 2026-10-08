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


"""Scrape trusted news feeds, match headlines to NSE tickers, score sentiment,
and store everything in news.db. Run as often as you like; duplicates are skipped.

Each article now also records, per company it names:
  * in_title  — named in the headline (a claim) vs only in the body blurb (noise)
  * noise     — the article is a tracker page / listicle / index wrap, not news
  * after_hours — it broke while the NSE was shut (the one window with real edge)
These land in article_tickers so llm_analyst.py can score EACH company separately
instead of stamping one article-level sentiment onto every name it mentions.

Usage: python monitor.py
"""
import json
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import UTC, datetime
from pathlib import Path

import db
import feedparser
from newslib import (
    classify_noise,
    is_after_hours,
    load_ticker_patterns,
    match_tickers,
    parse_feed_time,
    score_sentiment,
)
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

BASE = Path(__file__).parent
DB = BASE / "news.db"


def main():
    patterns = load_ticker_patterns(BASE / "tickers.csv")
    analyzer = SentimentIntensityAnalyzer()
    con = db.connect(DB)
    feeds = json.loads((BASE / "config.json").read_text())["feeds"]

    new_total, matched_total, noise_total = 0, 0, 0
    now = datetime.now(UTC).isoformat()

    for feed in feeds:
        parsed = feedparser.parse(feed["url"], agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        if parsed.bozo and not parsed.entries:
            print(f"[WARN] {feed['name']}: could not fetch ({parsed.get('bozo_exception')})")
            continue
        new_here = 0
        for entry in parsed.entries:
            link = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()[:500]
            # global feeds skip ticker matching: "Titan"/"Apollo" in world news
            # are usually not the NSE companies
            hits = {} if feed.get("global") else match_tickers(title, summary, patterns)
            n_title = sum(hits.values())
            noise = classify_noise(title, n_title)
            published = parse_feed_time(entry)
            sentiment = score_sentiment(f"{title}. {summary}", analyzer)
            # Record the sighting even when the article is a duplicate: source
            # trust must be graded on what an outlet actually carried, not on
            # which feed happened to be scraped first.
            con.execute("INSERT OR IGNORE INTO article_sources VALUES (?,?)", (link, feed["name"]))
            try:
                con.execute(
                    "INSERT INTO articles "
                    "(link, source, title, summary, published, fetched_at, "
                    "sentiment, tickers, llm_sent, noise, after_hours, "
                    "n_title_tickers) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        link,
                        feed["name"],
                        title,
                        summary,
                        published,
                        now,
                        sentiment,
                        ",".join(sorted(hits)),
                        None,
                        noise,
                        is_after_hours(published or now),
                        n_title,
                    ),
                )
            except sqlite3.IntegrityError:
                continue  # already seen
            # Only real news gets per-ticker rows; scoring a tracker page wastes
            # LLM budget and pollutes the scoreboard.
            if not noise:
                for symbol, in_title in hits.items():
                    con.execute(
                        "INSERT OR IGNORE INTO article_tickers "
                        "(link, symbol, in_title) VALUES (?,?,?)",
                        (link, symbol, in_title),
                    )
            new_here += 1
            if hits:
                matched_total += 1
            noise_total += noise
        con.commit()
        new_total += new_here
        print(f"[OK] {feed['name']}: {len(parsed.entries)} entries, {new_here} new")

    print(
        f"\n{new_total} new articles stored, {matched_total} matched to tickers "
        f"({noise_total} flagged as tracker/listicle/index noise).\n"
    )

    # Digest of new, real (non-noise) ticker-matched signals from this run
    rows = con.execute(
        "SELECT a.source, a.title, a.sentiment, a.tickers, a.after_hours "
        "FROM articles a WHERE a.fetched_at = ? AND a.tickers != '' "
        "AND COALESCE(a.noise, 0) = 0 ORDER BY a.sentiment DESC",
        (now,),
    ).fetchall()
    if rows:
        print("=== New signals ===")
        for source, title, sent, tickers, after in rows:
            label = "BULLISH" if sent >= 0.25 else "BEARISH" if sent <= -0.25 else "neutral"
            when = "[off-hours]" if after else ""
            print(f"[{label:7}] {tickers}  ({sent:+.2f}) {when} {title}  — {source}")
    con.close()


if __name__ == "__main__":
    main()
