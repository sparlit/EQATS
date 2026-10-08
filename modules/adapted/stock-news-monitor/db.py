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


"""The single definition of news.db's schema, with idempotent migration.

Every script opens the DB through `connect()` so a fresh clone and a long-running
checkout can never disagree about columns. Schema drift here is not theoretical:
a missing `llm_sent` column silently crashed every scrape for ~3.5 weeks in July
2026. Adding a column now means editing exactly one place.

Tables
------
articles          one row per fetched article (dedup key = link)
article_tickers   one row per (article, company) pair — where per-ticker scores
                  live. This is the fix for "one sentiment stamped on every
                  company an article mentions".
graded            per-pair grades written by scoreboard.py every run, via
                  INSERT OR REPLACE. NOT rebuilt and NOT pruned despite the
                  30-day framing — rows accumulate indefinitely.
                  ⚠️ NOTHING READS THIS TABLE. It is written and never queried.
                  LESSONS.md L5 claims source trust "comes from the `graded`
                  table"; it does not — both source_weights() implementations
                  (export_signal.py, autotrader.py) read `labels`. Do not act
                  on that claim: pruning or rebuilding `graded` changes no
                  behaviour, and deleting `labels` silently wipes the bot's
                  learned source trust. Kept because it is harmless and its
                  history is a record, but treat it as an unused artefact.
labels            the growing ML dataset (see ROADMAP_ML.md §1) AND the live
                  source of learned source trust. Richer than `graded`. Not
                  append-only in practice: scoreboard.py rewrites every row
                  inside the 30-day regrade window on each run, so a row's
                  values can change until it ages out.
verdicts          alerts.py's ✅ calls, graded at 5 days by scoreboard.py
"""
import sqlite3

_TABLES = [
    """CREATE TABLE IF NOT EXISTS articles (
        link TEXT PRIMARY KEY,
        source TEXT,
        title TEXT,
        summary TEXT,
        published TEXT,
        fetched_at TEXT,
        sentiment REAL,
        tickers TEXT,
        llm_sent REAL
    )""",
    """CREATE TABLE IF NOT EXISTS article_tickers (
        link TEXT,
        symbol TEXT,
        in_title INTEGER,
        llm_sent REAL,
        llm_novel INTEGER,
        PRIMARY KEY (link, symbol)
    )""",
    """CREATE TABLE IF NOT EXISTS graded (
        day TEXT, symbol TEXT, source TEXT, title TEXT,
        sent REAL, ret REAL, hit INT,
        PRIMARY KEY (day, symbol, source, title)
    )""",
    """CREATE TABLE IF NOT EXISTS labels (
        link TEXT, symbol TEXT, day TEXT, source TEXT, title TEXT,
        vader REAL, llm_sent REAL, llm_novel INTEGER,
        in_title INTEGER, after_hours INTEGER, n_sources INTEGER,
        ret_1d REAL, ret_3d REAL, ret_5d REAL,
        mkt_1d REAL, mkt_3d REAL, mkt_5d REAL,
        PRIMARY KEY (link, symbol)
    )""",
    """CREATE TABLE IF NOT EXISTS verdicts (
        ts TEXT, symbol TEXT, price REAL, title TEXT
    )""",
    # Articles are deduped by URL, so the FIRST feed to carry a story owns the
    # `articles.source` column forever — which made learned source trust partly
    # an artifact of the order feeds appear in config.json. This records every
    # outlet that carried a link, so trust is graded on what a source actually
    # published. See LESSONS.md L15.
    """CREATE TABLE IF NOT EXISTS article_sources (
        link TEXT, source TEXT,
        PRIMARY KEY (link, source)
    )""",
    # One-time data repairs record themselves here so they cannot run twice.
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT
    )""",
]

# Columns added after the original schema shipped. (table, column, decl)
_ADDED_COLUMNS = [
    ("articles", "llm_sent", "REAL"),
    ("articles", "noise", "INTEGER"),
    ("articles", "after_hours", "INTEGER"),
    ("articles", "n_title_tickers", "INTEGER"),
    # Replaces labels.n_sources, which counted per-symbol LIFETIME coverage with
    # no date bound and was recomputed every run, so an old row's value grew with
    # news published after it — future leakage into a P1 feature whose evaluation
    # protocol is walk-forward. n_sources is FROZEN, not redefined: rewriting it
    # in place would silently give in-window rows one meaning and out-of-window
    # rows another, with no marker. See meta['labels_schema'].
    ("labels", "n_sources_win", "INTEGER"),
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at)",
    "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published)",
    "CREATE INDEX IF NOT EXISTS idx_at_symbol ON article_tickers(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_asrc_source ON article_sources(source)",
]


def flag(con, key):
    """Has this one-time repair already run?"""
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_flag(con, key, value="done"):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
    con.commit()


def migrate(con):
    for stmt in _TABLES:
        con.execute(stmt)
    for table, column, decl in _ADDED_COLUMNS:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    for stmt in _INDEXES:
        con.execute(stmt)
    con.commit()
    return con


def connect(path):
    return migrate(sqlite3.connect(path))
