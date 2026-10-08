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


"""One-time (and re-runnable) backfill of the per-ticker schema over history.

Recomputes, for every article already in news.db:
  * ticker matches, split into headline mentions vs body-blurb mentions
  * the noise flag (tracker page / listicle / index wrap)
  * the after-hours flag
  * one article_tickers row per (article, company) pair

Safe to re-run — and you SHOULD re-run it after editing tickers.csv, so history
picks up newly covered companies. Nothing is ever deleted; junk is flagged.

Old article-level llm_sent scores are deliberately NOT copied onto the new pairs.
They were produced by the buggy prompt (one score stamped on every company) and
carry no novelty flag. Leaving them NULL means everything gets re-scored properly
by llm_analyst.py, which clears in a day or two and yields one consistent dataset.

Usage: python migrate.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import timedelta

import db
from newslib import classify_noise, is_after_hours, load_ticker_patterns, match_tickers, parse_ts

BASE = Path(__file__).parent
DB = BASE / "news.db"


TZ_REPAIR = "published_tz_shift_v1"

# Which alias set the CURRENT article_tickers rows were produced by. Recorded on
# every rescan, because a rescan is retroactive: editing tickers.csv rewrites
# in_title/tickers for the whole history, while scoreboard.py only rewrites
# `labels` inside its 30-day window. So an alias change gives rows on either side
# of the cut two different meanings for the same symbol, and this flag is the only
# marker of where the cut is. Bump the date+description on every alias edit.
# See LESSONS.md L21 and ROADMAP_ML.md §3.
ALIAS_REV = (
    "2026-07-31 bare 'Adani'/'Coal'/'Reliance'/'Persistent' blocked "
    "(sibling-listing and English-noun false positives); SBIN gains "
    "guarded 'SBI' regex; duplicate 'ET Markets Wrap' feed removed. "
    "Pre-cut ADANIENT rows mean 'Adani group', post-cut mean 'Adani "
    "Enterprises'; pre-cut SBIN rows are empty. A walk-forward split "
    "must not straddle this date without a flag."
)


def repair_published_timestamps(con):
    """One-time: undo the time.mktime() timezone bug on historical rows.

    Every `published` written before 2026-07-30 was produced by
    `time.mktime(published_parsed)`, which reads a UTC struct as LOCAL time.
    With TZ=Asia/Kolkata in the workflow that stamped each article exactly 5h30m
    early. Verified uniform: of 10 163 rows, 10 161 had a publish->scrape lag of
    >= 5.5h (impossible with hourly polling) and none were negative, so a single
    +5:30 shift is correct rather than a per-row guess.

    Guarded by a `meta` flag: migrate.py runs on every pipeline invocation and
    applying this twice would push every timestamp 11 hours into the future.
    """
    if db.flag(con, TZ_REPAIR):
        return 0
    rows = con.execute(
        "SELECT link, published FROM articles WHERE published IS NOT NULL"
    ).fetchall()
    fixed = 0
    for link, published in rows:
        dt = parse_ts(published)
        if dt is None:
            continue
        con.execute(
            "UPDATE articles SET published = ? WHERE link = ?",
            ((dt + timedelta(hours=5, minutes=30)).isoformat(), link),
        )
        fixed += 1
    db.set_flag(con, TZ_REPAIR, f"shifted {fixed} rows by +5:30")
    con.commit()
    return fixed


def backfill_article_sources(con):
    """Seed article_sources from the one source each link currently records."""
    if db.flag(con, "article_sources_seed_v1"):
        return 0
    n = con.execute(
        "INSERT OR IGNORE INTO article_sources (link, source) "
        "SELECT link, source FROM articles WHERE source IS NOT NULL"
    ).rowcount
    db.set_flag(con, "article_sources_seed_v1", f"seeded {n}")
    con.commit()
    return n


def main():
    con = db.connect(DB)
    patterns = load_ticker_patterns(BASE / "tickers.csv")

    shifted = repair_published_timestamps(con)
    if shifted:
        print(
            f"[repair] corrected {shifted} published timestamps by +5:30 "
            "(time.mktime timezone bug — one time only)"
        )
    seeded = backfill_article_sources(con)
    if seeded:
        print(f"[repair] seeded {seeded} article_sources rows")

    rows = con.execute(
        "SELECT link, title, summary, published, fetched_at, source FROM articles"
    ).fetchall()
    print(f"Rescanning {len(rows)} articles against {len(patterns)} alias patterns...")

    # Feeds flagged global skip ticker matching (see monitor.py); reproduce that
    # here so a re-run cannot invent matches the live scraper would never make.
    import json

    global_feeds = {
        f["name"]
        for f in json.loads((BASE / "config.json").read_text())["feeds"]
        if f.get("global")
    }

    pairs, noisy, changed = 0, 0, 0
    for link, title, summary, published, fetched_at, source in rows:
        hits = {} if source in global_feeds else match_tickers(title, summary, patterns)
        n_title = sum(hits.values())
        noise = classify_noise(title, n_title)
        con.execute(
            "UPDATE articles SET tickers = ?, noise = ?, after_hours = ?, "
            "n_title_tickers = ? WHERE link = ?",
            (",".join(sorted(hits)), noise, is_after_hours(published or fetched_at), n_title, link),
        )
        changed += 1
        noisy += noise
        # Drop pairs this article no longer matches, so a tickers.csv edit can
        # RETIRE a symbol as well as add one. Without this, renames leave ghosts
        # (ZOMATO.NS kept exporting a signal after it became ETERNAL.NS).
        keep = set() if noise else set(hits)
        if keep:
            placeholders = ",".join("?" * len(keep))
            con.execute(
                f"DELETE FROM article_tickers WHERE link = ? AND symbol NOT IN ({placeholders})",
                (link, *keep),
            )
        else:
            con.execute("DELETE FROM article_tickers WHERE link = ?", (link,))
        if not noise:
            for symbol, in_title in hits.items():
                con.execute(
                    "INSERT OR IGNORE INTO article_tickers (link, symbol, in_title) VALUES (?,?,?)",
                    (link, symbol, in_title),
                )
                # keep in_title current if aliases changed what matched where
                con.execute(
                    "UPDATE article_tickers SET in_title = ? WHERE link = ? AND symbol = ?",
                    (in_title, link, symbol),
                )
                pairs += 1
        if changed % 2000 == 0:
            con.commit()
            print(f"  ...{changed}")
    db.set_flag(con, "alias_rev", ALIAS_REV)
    con.commit()

    total_pairs = con.execute("SELECT COUNT(*) FROM article_tickers").fetchone()[0]
    unscored = con.execute(
        "SELECT COUNT(*) FROM article_tickers WHERE llm_sent IS NULL"
    ).fetchone()[0]
    matched = con.execute("SELECT COUNT(*) FROM articles WHERE tickers != ''").fetchone()[0]
    print(f"\nDone. {changed} articles rescanned.")
    print(f"  ticker-matched articles: {matched}")
    print(f"  flagged as noise:        {noisy}")
    print(f"  (article, company) pairs: {total_pairs}  — {unscored} awaiting LLM scoring")
    con.close()


if __name__ == "__main__":
    main()
