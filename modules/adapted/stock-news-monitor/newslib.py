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


"""Shared classification helpers used across the whole pipeline.

One place so monitor.py, llm_analyst.py, scoreboard.py, export_signal.py and
alerts.py all agree on: what counts as noise, what counts as ONE story, and when
a headline arrived relative to the NSE session.

Design note — two different filters, deliberately kept separate:
  * NOISE (here, regex): structurally not company news — auto-generated tracker
    pages, listicle/calendar previews, index wrap-ups. No company-specific claim
    exists to score, so these never reach the LLM and never get graded.
  * NOVELTY (llm_analyst): judgment on whether real news is NEW information or a
    description of a move that already happened ("Coal India shares fall 3%").
    That needs reading comprehension, not a regex, so the LLM decides it.
Keeping the regex conservative matters: over-filtering silently destroys signal.
"""
import calendar
import difflib
import os
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))


def atomic_write_text(path, text, encoding="utf-8"):
    """Write `text` to `path` so a reader can never see a half-written file.

    `Path.write_text` truncates first, then writes. If the process dies in
    between — a cancelled GitHub runner, the 6-hour job limit, a killed step —
    the file is left truncated. That matters here because the workflow commits
    with `if: always()`, so a corrupt file gets PUSHED, every later run fails
    reading it, and recovery needs a manual git revert.

    Write to a sibling temp file, fsync it, then os.replace: on both POSIX and
    Windows the rename is atomic, so the destination is either the old complete
    content or the new complete content. The temp file is removed on failure so
    a crashed write cannot leave *.tmp litter for the workflow's `git add`.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# NSE continuous session. Used for the after-hours flag, not for trading logic.
SESSION_OPEN = (9, 15)
SESSION_CLOSE = (15, 30)
SESSION_OPEN_MIN = SESSION_OPEN[0] * 60 + SESSION_OPEN[1]
SESSION_CLOSE_MIN = SESSION_CLOSE[0] * 60 + SESSION_CLOSE[1]

# NSE equity-segment trading holidays. Weekday holidays only matter; weekend
# ones are already covered. UPDATE THIS EVERY DECEMBER for the coming year —
# a missing entry means the bot believes a shut market is open and "trades" at
# a stale close, which is exactly the class of bug LESSONS.md L5 records.
#
# Error asymmetry, which is why the 2027 rows below are here despite being
# provisional: a date wrongly PRESENT costs one skipped trading day. A date
# wrongly ABSENT is the impossible-fill bug. Over-inclusion is the safe side.
#
# This list is never the real protection — session_data_fresh() is, because it
# asks the index whether a bar exists today instead of trusting a hand-typed
# set. Both entries and exits go through it (see autotrader.market_phase and
# autotrader.main).
NSE_HOLIDAYS = {
    # 2026 — from the NSE holiday circular (verified 2026-07-30).
    "2026-01-15",
    "2026-01-26",
    "2026-03-03",
    "2026-03-26",
    "2026-03-31",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-05-28",
    "2026-06-26",
    "2026-09-14",
    "2026-10-02",
    "2026-10-20",
    "2026-11-10",
    "2026-11-24",
    "2026-12-25",
    # 2027 — PROVISIONAL. Compiled 2026-07-31 from a published third-party 2027
    # calendar, NOT from an NSE circular (NSE issues that in December). Only the
    # weekday entries are listed; the weekend ones need no entry. REPLACE THIS
    # BLOCK WITH THE OFFICIAL CIRCULAR IN DECEMBER 2026 — the lunar-calendar
    # dates (Id, Holi, Muharram, Diwali) are the ones that move, and Diwali in
    # particular usually also carries a separate Muhurat session NSE announces
    # late. Before this block existed the set had ZERO 2027 entries, so
    # is_trading_day(2027-01-26) returned True on Republic Day.
    "2027-01-26",  # Tue  Republic Day          (fixed date, certain)
    "2027-03-10",  # Wed  Id-ul-Fitr            (lunar, verify)
    "2027-03-22",  # Mon  Holi                  (lunar, verify)
    "2027-03-26",  # Fri  Good Friday
    "2027-04-14",  # Wed  Ambedkar Jayanti      (fixed date, certain)
    "2027-04-15",  # Thu  Ram Navami            (lunar, verify)
    "2027-04-19",  # Mon  Mahavir Jayanti       (lunar, verify)
    "2027-05-17",  # Mon  Bakri Id              (lunar, verify)
    "2027-06-15",  # Tue  Muharram              (lunar, verify)
    "2027-10-29",  # Fri  Diwali / Balipratipada (lunar, verify)
}


def is_trading_day(d):
    """True if the NSE holds a normal session on this IST date."""
    if isinstance(d, datetime):
        d = d.date()
    return d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS


def parse_feed_time(entry):
    """UTC ISO timestamp from a feedparser entry, or None.

    Uses calendar.timegm, NOT time.mktime. feedparser always returns
    published_parsed in UTC; time.mktime interprets a struct_time as LOCAL time,
    so with TZ=Asia/Kolkata set in the workflow it stamped every article 5.5
    hours early — silently, from day one. timegm is timezone-independent, so
    this cannot regress if someone changes TZ. See LESSONS.md L11.
    """
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=UTC).isoformat()
    return None


# Articles naming more than this many companies are listicles/previews: one
# sentiment cannot honestly be attributed to each name.
MAX_TICKERS_BEFORE_LISTICLE = 3

_NOISE_SOURCES = [
    # --- auto-generated per-stock tracker pages (the single biggest polluter) ---
    r"share price (highlights|live updates?|history|target)",
    r"stock price history",
    r"share price (today|live)\b",
    # --- listicle / calendar previews: many names, no claim about any of them ---
    r"\bstocks? to watch\b",
    r"\bstock picks?\b",
    r"\btop stocks to (buy|sell)\b",
    r"\bbuy,? sell,? (or )?hold\b",
    r"\bstock recommendations?\b",
    r"\bmarket trading guide\b",
    r"results live( updates)?\b",
    r"\bamong (companies|more than|\d+|stocks)\b",
    r"\bfull list here\b",
    r"\bto declare .{0,30}(results|earnings)\b",
    r"\bex-date\b",
    # --- index / market wrap-ups: describe the market, not a company ---
    r"\bmarket (wrap|close|live|highlights|outlook)\b",
    r"\b(closing|opening) bell\b",
    r"\btop (gainers|losers)\b",
    r"\bmcap of\b",
    r"\bsensex\b",
    r"\bearnings central\b",
    r"\b(stock|equity) markets?\b[^.]{0,30}\b(decline|rise|fall|gain|end|close|open|slip)",
    r"\bnifty (\d+|it|bank|pack|pharma|auto|metal)\b",
    r"\bnifty\b[^.]{0,40}\b(jumps?|slips?|falls?|rises?|gains?|ends?|closes?|premium)\b",
    # --- not company news at all ---
    r"\bbank holidays?\b",
    r"\brbi calendar\b",
]
NOISE_TITLE = re.compile("|".join(_NOISE_SOURCES), re.IGNORECASE)

# Finance-aware direction words; VADER alone misreads headlines like
# "profit falls 19%, declares dividend" as positive.
UP_WORDS = re.compile(
    r"\b(rises?|rally|rallies|jumps?|gains?|surges?|soars?|climbs?|beats?|"
    r"advances?|rebounds?|upgrades?|record high|buy call)\b",
    re.IGNORECASE,
)
DOWN_WORDS = re.compile(
    r"\b(falls?|drops?|slips?|plunges?|declines?|tumbles?|sinks?|crashes?|"
    r"slides?|bleeds?|misses?|downgrades?|weak|losses?|loss)\b",
    re.IGNORECASE,
)


def score_sentiment(text, analyzer):
    """VADER blended with finance direction words when any are present."""
    vader = analyzer.polarity_scores(text)["compound"]
    ups, downs = len(UP_WORDS.findall(text)), len(DOWN_WORDS.findall(text))
    if ups + downs == 0:
        return vader
    fin = (ups - downs) / (ups + downs)
    return round(0.4 * vader + 0.6 * fin, 4)


def classify_noise(title, n_title_tickers=0):
    """1 if this headline carries no scoreable company-specific claim.

    Matched on the TITLE only — a passing mention of "Sensex" inside a company
    story must not disqualify it. Likewise the listicle rule counts companies
    named in the HEADLINE, not ones the body blurb happens to mention: an article
    headlined "Jindal Steel Q1 profit falls 44%" is real news even if its summary
    name-drops four peers.
    """
    if NOISE_TITLE.search(title or ""):
        return 1
    if n_title_tickers > MAX_TICKERS_BEFORE_LISTICLE:
        return 1
    return 0


# An alias starting with this prefix is used as a RAW regex instead of being
# escaped, so a short abbreviation can carry its own collision guard. Needed for
# exactly one real case: Indian headlines write "SBI", never "State Bank of
# India", but "SBI Card(s)" and "SBI Life" are DIFFERENT listed companies
# (SBICARD.NS, SBILIFE.NS). A plain "SBI" alias would steal their headlines, so
# SBIN.NS carries `re:\bSBI\b(?!\s+Cards?\b)(?!\s+Life\b)` instead.
# NOTE: `|` is the alias separator in tickers.csv, so a regex alias must express
# alternation with repeated lookaheads or character classes, never a pipe.
RE_ALIAS = "re:"


def load_ticker_patterns(path):
    """[(alias_regex, symbol)] from a tickers.csv with symbol,aliases,sector."""
    import csv

    patterns = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for alias in row["aliases"].split("|"):
                alias = alias.strip()
                if not alias:
                    continue
                if alias.startswith(RE_ALIAS):
                    # already carries its own boundaries and guards
                    patterns.append(
                        (re.compile(alias[len(RE_ALIAS) :], re.IGNORECASE), row["symbol"])
                    )
                    continue
                # word-boundary match so "ITC" doesn't fire inside "pitch"
                patterns.append(
                    (re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE), row["symbol"])
                )
    return patterns


def match_tickers(title, summary, patterns):
    """Return {symbol: in_title} for every company this article names.

    `in_title` separates a headline claim ("HDFC Bank fines CEO") from a passing
    mention in the body blurb. They are worth very different amounts and the old
    code conflated them, which is how single-company stories ended up tagged with
    four peers and flagged as listicles.
    """
    title = title or ""
    body = f"{title}. {summary or ''}"
    found = {}
    for pat, sym in patterns:
        if sym in found and found[sym]:
            continue
        if pat.search(title):
            found[sym] = 1
        elif pat.search(body):
            found.setdefault(sym, 0)
    return found


def _normalize(title):
    return re.sub(r"\W+", " ", (title or "").lower()).strip()


def cluster_titles(titles, threshold=0.85):
    """Group near-identical headlines so syndicated wire copy counts once.

    Returns a list of cluster indexes parallel to `titles`. One PTI/Reuters story
    reprinted by eight outlets is ONE story, not eight-source confirmation — the
    distinction the exporter's `sources` count depends on.
    """
    reps, out = [], []
    for t in (_normalize(x) for x in titles):
        for i, c in enumerate(reps):
            if difflib.SequenceMatcher(None, t, c).ratio() > threshold:
                out.append(i)
                break
        else:
            reps.append(t)
            out.append(len(reps) - 1)
    return out


def distinct_stories(titles, threshold=0.85):
    """How many genuinely independent stories are in this list of headlines."""
    return len(set(cluster_titles(titles, threshold))) if titles else 0


def parse_ts(ts):
    """Parse an ISO timestamp to an aware UTC datetime, or None."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def is_after_hours(ts):
    """1 if the headline landed while the NSE was shut, else 0 (None if unknown).

    This is the hypothesis the whole project rests on: news breaking after the
    15:30 close or before the 09:15 open cannot be acted on by anyone in India
    until the next session, so it is the one window where a headline may not be
    priced in yet. Everything else is usually already in the tape.
    """
    dt = parse_ts(ts)
    if dt is None:
        return None
    ist = dt.astimezone(IST)
    if not is_trading_day(ist.date()):  # weekend or NSE holiday
        return 1
    minutes = ist.hour * 60 + ist.minute
    return 0 if SESSION_OPEN_MIN <= minutes <= SESSION_CLOSE_MIN else 1


def signal_trading_day(ts):
    """The NSE trading day whose CLOSE is the right baseline for this headline.

    Not simply the calendar date, and this distinction is the whole ballgame for
    the after-hours hypothesis:

      * news at 20:00 IST Wednesday  -> Wednesday. The last close before anyone
        could act was Wednesday's; the trade happens at Thursday's open.
      * news at 02:00 IST Thursday   -> ALSO Wednesday, because Thursday has not
        opened yet. Attributing it to Thursday would take Thursday's close as
        the baseline and measure Thu->Fri, quietly discarding the opening gap —
        i.e. discarding exactly the move an overnight signal is supposed to
        capture.
      * news at 11:00 IST Thursday   -> Thursday (intraday; the baseline close
        already contains it, which is the conservative reading).

    Rolls back over weekends and holidays to a real trading day.
    """
    dt = parse_ts(ts)
    if dt is None:
        return None
    ist = dt.astimezone(IST)
    d = ist.date()
    if ist.hour * 60 + ist.minute < SESSION_OPEN_MIN:
        d -= timedelta(days=1)  # arrived before today's open
    guard = 0
    while not is_trading_day(d) and guard < 10:
        d -= timedelta(days=1)
        guard += 1
    return d
