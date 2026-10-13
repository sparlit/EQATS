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


"""Export a per-ticker news-sentiment snapshot for other projects to consume.

Writes news_signal.json: for each NSE ticker with recent coverage, an aggregate
sentiment in [-1, 1]. This is the clean hand-off point — the trading-bot's fused
momentum+news bot reads this file (locally, or from the raw GitHub URL on CI)
instead of touching news.db.

What each article's weight is built from:
  source trust   learned from the `labels` table's 1-day EXCESS returns (a
                 source that grades badly counts less). NOT from the `graded`
                 table, which nothing reads - see db.py (NM-11)
  recency        half-life decay, newest news dominates
  novelty        the LLM's judgment that this is NEW information, not a
                 description of a move that already happened. Descriptive items
                 are kept but heavily discounted.
  headline vs body  a company named in the headline is the subject; one named in
                 the body blurb is usually a passing mention

What a consumer should gate on
------------------------------
`score` alone is NOT enough, and this is the defect the whole file was missing:
score = Σ(sentᵢ·wᵢ) / Σ(wᵢ) is SCALE-INVARIANT, so multiplying every weight for a
symbol by the same constant leaves it unchanged. Whenever a symbol's items all
share a property — all non-novel, all one outlet, all the same age — the novelty
discount, the learned source trust and the recency decay cancel out completely.
Measured 2026-07-30: 41 of 84 exported symbols had novel==0 on EVERY item, so
NOVEL_DISCOUNT was inert for half the file, and one VADER reading of a single
preview headline exported at +0.97 — indistinguishable from a corroborated,
LLM-scored, multi-outlet event.

So four orthogonal facts are published alongside the score:
  conf        Σ(wᵢ) capped at 1.0 — the evidence WEIGHT behind the score, the
              dimension the division throws away. Multiply the score by it.
  n_outlets   distinct publisher domains
  n_days      distinct publication days — the event proxy. A single injected or
              single-blog headline is 1 outlet / 1 day and can never be
              corroborated; a real multi-day earnings event is not.
  n_articles  raw article count (the old `n`)

`sources` is DEPRECATED and does not mean what its name says. It is meant to be
independent-story count, but `cluster_titles` needs 0.85 title similarity and
real re-headlined wire copy shares almost no surface form, so it collapses ~3% of
titles and is ≈ n for nearly every ticker. Threshold tuning was measured and does
not fix it (day-bucketing is the only thing that bites). The field is kept
unchanged so no consumer breaks; gate on n_outlets/n_days/conf instead.

Usage: python export_signal.py
"""
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib

import db
from newslib import cluster_titles

BASE = Path(__file__).parent
DB = BASE / "news.db"
OUT = BASE / "news_signal.json"
STATUS = BASE / "pipeline_status.json"

SCHEMA = 2  # bump when a field's MEANING changes, not when adding one
CONF_REF = 2.0  # weight of ~two fresh, trusted, novel items = full confidence

WINDOW_DAYS = 7  # how far back news still counts toward "current" sentiment
MIN_ABS = 0.15  # ignore near-neutral noise when aggregating
HALF_LIFE_DAYS = 3.0  # older articles decay: weight halves every 3 days
NOVEL_DISCOUNT = 0.3  # weight for news the LLM judged already-priced-in
# Companies named ONLY in an article's body blurb are excluded, not discounted.
# Measured 2026-07-30 over 30 days: body-only mentions beat NIFTY 32.6% of the
# time (n=95, ±9.4) versus 51.1% for headline mentions — the whole confidence
# interval sits below coin-flip, i.e. they are actively anti-predictive. They
# keep flowing into news.db as an ML feature; they just don't reach the bot.
REQUIRE_HEADLINE = True


def source_weights(con):
    """Trust per source, learned from `labels` 1-day outcomes (0.6-1.4).

    Reads `labels`, NOT the `graded` table. LESSONS.md L5 says otherwise and is
    wrong; nothing reads `graded`. Deleting `labels` wipes these weights.

    Joined through article_sources on the article LINK, so an outlet is credited
    for every story it actually carried. Grading via articles.source alone gave
    the credit to whichever feed config.json happened to list first, which made
    learned trust partly an artifact of file ordering (LESSONS.md L15).

    Graded on EXCESS return vs NIFTY, so a source is not rewarded for market drift.
    """
    try:
        rows = con.execute(
            "SELECT s.source, "
            "       AVG(CASE WHEN (COALESCE(l.llm_sent, l.vader) > 0) "
            "                  = ((l.ret_1d - COALESCE(l.mkt_1d, 0)) > 0) "
            "            THEN 1.0 ELSE 0.0 END), "
            "       COUNT(*) "
            "FROM labels l JOIN article_sources s ON s.link = l.link "
            "WHERE l.ret_1d IS NOT NULL "
            "  AND ABS(COALESCE(l.llm_sent, l.vader)) >= 0.25 "
            "GROUP BY s.source"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {s: max(0.6, min(1.4, 2 * hr)) for s, hr, n in rows if n >= 5}


def outlet_of(link):
    """Publisher host for an article link: 'https://www.X.com/a' -> 'x.com'."""
    host = urlparse(link or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def health(con):
    """(pipeline_ok, failed_steps, data_through) for this run.

    run_pipeline.py writes pipeline_status.json immediately before invoking this
    script — it is the last step, so every upstream failure is known by now.
    Absent (hand-run, or an older runner) is treated as healthy.

    `data_through` is the real freshness number: `generated_at` only says when
    this file was written, which a broken scrape republishes just as promptly as
    a working one. That is how a dead pipeline stayed invisible for ~3.5 weeks.
    """
    status = {"ok": True, "failed": []}
    with contextlib.suppress(OSError, ValueError):
        status.update(json.loads(STATUS.read_text(encoding="utf-8")))
    through = con.execute("SELECT MAX(COALESCE(published, fetched_at)) FROM articles").fetchone()[0]
    return bool(status.get("ok", True)), list(status.get("failed", [])), through


def main():
    con = db.connect(DB)
    sw = source_weights(con)
    now = datetime.now(UTC)
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    pipeline_ok, failed_steps, data_through = health(con)

    rows = con.execute(
        "SELECT t.symbol, a.source, a.title, a.sentiment, t.llm_sent, "
        "       t.llm_novel, t.in_title, COALESCE(a.published, a.fetched_at), "
        "       a.link "
        "FROM article_tickers t JOIN articles a ON a.link = t.link "
        "WHERE COALESCE(a.noise, 0) = 0 "
        "  AND COALESCE(a.published, a.fetched_at) >= ?",
        (since,),
    ).fetchall()
    llm_scored = sum(1 for r in rows if r[4] is not None)

    # symbol -> [weighted_sum, weight_sum, n, [titles], novel_n, {outlets}, {days}]
    agg = {}
    for symbol, source, title, vader, llm, novel, in_title, ts, link in rows:
        if REQUIRE_HEADLINE and not in_title:
            continue
        sent = llm if llm is not None else vader
        if sent is None or abs(sent) < MIN_ABS:
            continue
        try:
            age_days = (now - datetime.fromisoformat(ts)).total_seconds() / 86400
        except (ValueError, TypeError):
            # Junk dates are real: news.db holds 19 articles published before
            # 2020. Treating an unparseable stamp as age 0 gave it the MAXIMUM
            # recency weight, i.e. promoted broken metadata to breaking news.
            continue
        w = sw.get(source, 1.0) * 0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)
        # novel is NULL for pairs the LLM has not reached yet — treat as unknown
        # (no discount) rather than assuming stale.
        if novel == 0:
            w *= NOVEL_DISCOUNT
        a = agg.setdefault(symbol, [0.0, 0.0, 0, [], 0, set(), set()])
        a[0] += sent * w
        a[1] += w
        a[2] += 1
        a[3].append(title)
        a[4] += 1 if novel else 0
        if outlet_of(link):
            a[5].add(outlet_of(link))
        a[6].add(ts[:10])

    signal = {}
    for symbol, (ws, wsum, n, titles, novel_n, outlets, days) in agg.items():
        if wsum <= 0:
            continue
        signal[symbol] = {
            "score": round(ws / wsum, 4),  # trust+recency+novelty weighted
            # The evidence weight the score's division discards. Without it a
            # single thin headline and a corroborated event look identical.
            "conf": round(min(1.0, wsum / CONF_REF), 3),
            "n_articles": n,
            "n_outlets": len(outlets),  # distinct publisher domains
            "n_days": len(days),  # distinct publication days
            "novel": novel_n,  # how many were new information
            "n": n,  # deprecated alias of n_articles
            "sources": len(set(cluster_titles(titles))),  # DEPRECATED, see docstring
        }

    out = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "data_through": data_through,
        "pipeline_ok": pipeline_ok,
        "failed_steps": failed_steps,
        "articles_in_window": len(rows),
        "pairs_llm_scored": llm_scored,
        "window_days": WINDOW_DAYS,
        "half_life_days": HALF_LIFE_DAYS,
        "note": "Per-ticker news sentiment. Scores are per-(article,company) LLM "
        "judgments weighted by learned source trust, recency, novelty and "
        "headline-vs-body position. GATE ON: 'conf' (evidence weight, "
        "0-1 — multiply the score by it), 'n_outlets' and 'n_days' "
        "(require >=2 of each before letting news veto or sell: one "
        "crafted or single-blog headline is 1 outlet on 1 day). "
        "'sources' is DEPRECATED — it counts articles, not independent "
        "stories, and is ~= n_articles for nearly every ticker; do not "
        "gate on it. Check pipeline_ok and data_through before use: "
        "generated_at only says when this file was written. "
        "articles_in_window counts (article,company) pairs; "
        "pairs_llm_scored is how many carry a real LLM score rather "
        "than the article-level VADER fallback.",
        "tickers": dict(sorted(signal.items())),
    }
    # Atomic: this file is committed and pushed for a real-money bot to read, so
    # a run killed mid-write must never leave a truncated JSON behind.
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    os.replace(tmp, OUT)
    con.close()

    strong = sorted(signal.items(), key=lambda kv: kv[1]["score"])
    print(
        f"Exported {len(signal)} tickers to {OUT.name} "
        f"(window {WINDOW_DAYS}d, {len(rows)} scored pairs)."
    )
    pct = f" ({100 * llm_scored / len(rows):.0f}%)" if rows else ""
    print(
        f"  pipeline_ok={pipeline_ok} data_through={data_through} "
        f"llm-scored {llm_scored}/{len(rows)} pairs{pct}"
    )
    if failed_steps:
        print(f"  failed steps: {', '.join(failed_steps)}")
    thin = [t for t, v in signal.items() if v["n_outlets"] < 2 or v["n_days"] < 2]
    print(
        f"  {len(thin)} of {len(signal)} tickers are single-outlet or "
        f"single-day (not corroborated — must not veto or sell)."
    )
    if strong:
        neg = [f"{t} {v['score']:+.2f}" for t, v in strong[:3] if v["score"] < 0]
        pos = [f"{t} {v['score']:+.2f}" for t, v in strong[::-1][:3] if v["score"] > 0]
        if neg:
            print("  most negative:", ", ".join(neg))
        if pos:
            print("  most positive:", ", ".join(pos))


if __name__ == "__main__":
    main()
