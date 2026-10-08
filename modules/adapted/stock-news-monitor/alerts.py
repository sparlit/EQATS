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


"""Scan recent articles and bot portfolio state; write a structured ALERT.md.

Two accounts are tracked, both starting at Rs 5,000 on 2026-07-02:
the BOT (autotrader.py, trades itself) and the NIFTY 50 shadow. The old
"you + Claude" manual account was retired 2026-07-30 — it required research
Ankit had no time to do, so its P&L measured nothing.

Sections: bot P&L vs the NIFTY shadow, news on stocks the bot holds, pre-checked
buy ideas (✅ ones are logged to the verdicts table so scoreboard.py can grade
them later), macro events mapped to exposed holdings, and a once-a-week report
with feed health (fired by the `weekly_last` marker in `meta`, not by a wall-clock
instant no scheduled run ever hits). The cloud workflow turns ALERT.md into a
GitHub issue (emailed by GitHub); the first line becomes the subject.

Company sections read `article_tickers` — headline mentions only, noise excluded,
per-(headline, company) scores in preference to article-level VADER. The macro
section is deliberately exempt from the noise flag: an index wrap makes no claim
about any one company, which is why it is flagged, and is exactly what that
section is for. Every feed-supplied string goes through md() before it reaches the
markdown, because GitHub renders issue bodies and nobody controls RSS titles.
"""
import csv
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import db
from newslib import atomic_write_text, distinct_stories

BASE = Path(__file__).parent
OUT = BASE / "ALERT.md"

WINDOW_HOURS = 1.2  # slightly over the hourly run cadence so nothing slips between runs
HELD_THRESHOLD = 0.4
OPPORTUNITY_THRESHOLD = 0.7
MAX_OPPORTUNITIES = 6
MAX_MACRO = 4
PRICED_IN_MOVE = 2.5  # % move that means the news is likely already in the price
MIN_OUTLETS = 2
MAX_CHECKED = 8  # bound on price lookups per email
# The weekly block used to require `weekday() == 6 and hour == 18` — Sunday 18:00
# IST. The pipeline is triggered at 08:15 / 09:30-14:30 / 15:45 / 20:00 / 02:30 on
# weekdays and 10:00 / 20:00 at weekends, so that instant is never reached and the
# section — including FEED_SILENT_HOURS, the project's ONLY zombie-feed detector —
# could not run at all. LESSONS.md L17 found six dead feeds by hand for exactly
# this reason. Replaced with a fire-once-per-week marker in `meta`, so whichever
# run happens to be first after the interval elapses renders it.
WEEKLY_FLAG = "weekly_last"
WEEKLY_EVERY_DAYS = 6
# The index shadow both accounts are measured against. Lived in portfolio.json
# until that manual account was retired; it is a fixed anchor, not state.
BENCHMARK = {
    "symbol": "^NSEI",
    "start_level": 24175.7,
    "start_capital": 5000.0,
    "start_date": "2026-07-02",
}
FEED_SILENT_HOURS = 48

MACRO_EVENT = re.compile(
    r"\b(crash(es|ed)?|plunge[sd]?|tumble[sd]?|sink(s|ing)?|black monday|"
    r"rate (hike|cut)|repo rate|circuit|emergency|war|strike[sd]?|sanction|"
    r"tariff|default|recession|inflation (surge|spike|shock))\b",
    re.IGNORECASE,
)
MACRO_SCOPE = re.compile(
    r"\b(sensex|nifty|dalal street|rbi|fed|federal reserve|wall street|"
    r"crude|oil|opec|rupee|dollar|gold|china|us market)\b",
    re.IGNORECASE,
)

# Index wrap-ups mention many tickers but aren't stock-specific news;
# they repeat every session and would spam ticker alerts
MARKET_WRAP = re.compile(
    r"\b(sensex|nifty|stock market|market live|top gainers|top losers|"
    r"opening bell|closing bell|market highlights)\b",
    re.IGNORECASE,
)

# macro keyword -> sectors it usually moves; used to tag which holdings
# a macro headline touches
EXPOSURE = [
    (re.compile(r"\b(crude|oil|opec|fuel)\b", re.IGNORECASE), {"energy"}),
    (
        re.compile(
            r"\b(rate hike|rate cut|repo rate|rbi|fed|federal reserve|inflation)\b", re.IGNORECASE
        ),
        {"banks", "financials", "auto"},
    ),
    (re.compile(r"\b(china|tariff|sanction|trade war)\b", re.IGNORECASE), {"metals", "auto", "it"}),
    (re.compile(r"\b(rupee|dollar)\b", re.IGNORECASE), {"it", "pharma"}),
    (re.compile(r"\b(war|geopolitic\w*)\b", re.IGNORECASE), {"energy", "metals"}),
]

REVIEW_ADVICE = (
    "👉 **What to do:** Read the full story first. Sell only if the problem is "
    "fundamental — profit collapse, fraud, regulator action, lost business. If it's "
    "a broad market dip or one analyst's opinion, holding is usually right. You never "
    "have to act in minutes; a real problem will still be true tomorrow."
)
SUPPORT_ADVICE = (
    "👉 **What to do:** Nothing — this is supportive news on a stock you already own. "
    "Avoid buying more just because it's up today; that gain is already in the price."
)
MIXED_ADVICE = (
    "👉 **What to do:** Signals conflict — read both sides before doing anything. "
    "When in doubt with conflicting news, doing nothing is a valid decision."
)
OPPORTUNITY_ADVICE = (
    "👉 **What to do:** The checks above are automated: *today's move* tests if the "
    "news is already priced in, *outlets/stories* tests independent confirmation, and "
    "the share count respects the sizing rule (max half your free cash on one idea). "
    "A ✅ is a shortlist, not an order — still read the story before buying."
)
MACRO_ADVICE = (
    "👉 **What to do:** Don't buy or sell from a macro headline alone — it moves whole "
    "sectors, slowly. If one of your holdings is tagged above, watch that position more "
    "closely today. If nothing is tagged, this is background noise for your book."
)


def dot(x):
    return "🔴" if x < 0 else "🟢"


# GitHub RENDERS issue bodies, and these bodies are built from RSS titles nobody
# controls. Unescaped, a headline containing `![](http://x/px.png)` becomes a
# tracking pixel that fires when the emailed issue is opened,
# `[click here](http://x)` becomes a plausible link inside a trusted automated
# notification, and `@someone` becomes a real mention. The issue TITLE is safe
# (built from machine-generated counts) — only the body needed this.
_MD_ESCAPE = re.compile(r"([\\`*_\[\]()<>#!|~@&])")


def md(text):
    """Escape feed-supplied text so markdown renders it as literal characters."""
    return _MD_ESCAPE.sub(r"\\\1", str(text or "")).replace("\r", " ").replace("\n", " ")


def load_sectors():
    with open(BASE / "tickers.csv", encoding="utf-8") as f:
        return {row["symbol"]: row.get("sector", "") for row in csv.DictReader(f)}


def get_prices(symbols):
    from paper_portfolio import live_price

    prices = {}
    for s in symbols:
        try:
            prices[s] = live_price(s)
        except (Exception, SystemExit):
            prices[s] = None
    return prices


def book_lines(held, cash, bench, prices):
    from paper_portfolio import STARTING_CASH

    out = [
        "",
        "## 🤖 The bot's book",
        "",
        "| stock | qty | avg cost | now | P&L |",
        "|---|---:|---:|---:|---|",
    ]
    total = cash
    for t, pos in held.items():
        price = prices.get(t) or pos["avg_cost"]
        cost = pos["avg_cost"] * pos["qty"]
        pnl = price * pos["qty"] - cost
        total += price * pos["qty"]
        out.append(
            f"| {t} | {pos['qty']} | {pos['avg_cost']:.2f} | {price:.2f} "
            f"| {dot(pnl)} {pnl:+.2f} ({100 * pnl / cost:+.2f}%) |"
        )
    out.append(
        f"\n**Total: Rs {total:,.2f} ({total - STARTING_CASH:+.2f}, "
        f"{100 * (total - STARTING_CASH) / STARTING_CASH:+.2f}% since start) "
        f"— incl. Rs {cash:,.2f} cash**"
    )
    level = bench and prices.get(bench["symbol"])
    shadow = bench["start_capital"] * level / bench["start_level"] if level else None
    return out, total, shadow


def bot_recent_trades():
    ledger = BASE / "bot_portfolio.json"
    if not ledger.exists():
        return [], None
    b = json.loads(ledger.read_text())
    cutoff = (datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)).isoformat()
    return [t for t in b["trades"] if t["time"] >= cutoff], b


def bot_lines(bot, recent, bot_total, shadow):
    """Scoreboard vs the index, this window's trades, and the closed-trade record.

    `bot_total` comes from book_lines, which already priced this exact book —
    the two used to be separate accounts, so this recomputed it (and re-fetched
    every price) needlessly.
    """
    if bot is None:
        return []
    out = ["", "## 📊 Bot vs index", "", "| account | value | since start |", "|---|---:|---:|"]
    out.append(f"| 🤖 bot | Rs {bot_total:,.2f} | {100 * (bot_total - 5000) / 5000:+.2f}% |")
    if shadow:
        out.append(f"| NIFTY 50 index | Rs {shadow:,.2f} | {100 * (shadow - 5000) / 5000:+.2f}% |")
    if recent:
        out.append("\n**Bot trades this hour:**")
        for t in recent:
            # `reason` embeds the headline that triggered the trade — feed text.
            out.append(
                f"- {t['action'].upper()} {t['qty']} x {t['symbol']} @ "
                f"Rs {t['price']:.2f} — {md(t.get('reason', ''))}"
            )
    closed = bot.get("closed", [])
    if closed:
        wins = sum(1 for c in closed if c["win"])
        out.append(
            f"Bot record: {wins}/{len(closed)} wins, "
            f"avg {sum(c['pnl_pct'] for c in closed) / len(closed):+.2f}% per closed trade"
        )
    return out


def opportunity_checks(opps, cash, con, now):
    """Pre-buy checklist per ticker; log ✅ PASSES to the verdicts table."""
    import yfinance as yf

    day_ago = (now - timedelta(hours=24)).isoformat()
    cap = cash / 2
    lines = ["", "**🤖 Pre-buy checks, done for you:**", ""]
    checked = []
    for sent, tks, title, _source in opps:
        for t in tks:
            if t in checked or len(checked) >= MAX_CHECKED:
                continue
            checked.append(t)
            if sent < 0:
                lines.append(
                    f"- `{t}`: ℹ️ bad-news signal on a stock you don't own — "
                    "nothing to do (no short selling)."
                )
                continue
            # Confirmation must be measured the way every other consumer measures
            # it: real news only (noise = 0), HEADLINE mentions only (in_title = 1,
            # because body-only mentions measured 38.3% excess, n=193 — worse than
            # a coin flip), and per-(headline, company) scores in preference to the
            # one article-level VADER reading stamped on every name it mentions.
            # This query used to read `articles.tickers` with no filter at all, so
            # a listicle preview could supply the "independent coverage" behind a
            # ✅ PASSES verdict that scoreboard.py then graded (LESSONS.md L22).
            cov = con.execute(
                "SELECT a.source, a.title FROM article_tickers tk "
                "JOIN articles a ON a.link = tk.link "
                "WHERE tk.symbol = ? AND tk.in_title = 1 "
                "  AND COALESCE(a.noise, 0) = 0 AND a.fetched_at >= ? "
                "  AND ABS(COALESCE(tk.llm_sent, a.sentiment)) >= 0.25",
                (t, day_ago),
            ).fetchall()
            outlets = len({s for s, _ in cov})
            stories = distinct_stories([ttl for _, ttl in cov])
            try:
                # dropna: mid-session yfinance emits placeholder rows with NaN
                # closes. NaN is truthy, so it sails past `if price` below and
                # only dies at int() — guard it here where the data enters.
                closes = yf.Ticker(t).history(period="2d")["Close"].dropna()
                price = float(closes.iloc[-1]) if len(closes) else None
                move = (
                    (price / float(closes.iloc[-2]) - 1) * 100
                    if price is not None and len(closes) >= 2
                    else None
                )
            except Exception:
                price, move = None, None

            facts = [
                f"today {move:+.1f}%" if move is not None else "today's move n/a",
                f"{outlets} outlet(s), {stories} distinct stor{'y' if stories == 1 else 'ies'}",
            ]
            shares = int(cap // price) if price else 0
            if move is not None and move >= PRICED_IN_MOVE:
                verdict = f"❌ SKIP — already up {move:+.1f}% today, news likely priced in"
            elif outlets < MIN_OUTLETS or stories < 2:
                verdict = "⚠️ WAIT — not independently confirmed yet; look again if more report it"
            elif price is None:
                verdict = "⚠️ WAIT — no price data to verify"
            elif shares == 0:
                verdict = (
                    f"❌ SKIP — 1 share (Rs {price:,.2f}) exceeds your Rs {cap:,.0f} sizing cap"
                )
            else:
                verdict = f"✅ PASSES — you could buy up to {shares} share(s) @ ~Rs {price:,.2f}"
                dup = con.execute(
                    "SELECT 1 FROM verdicts WHERE symbol = ? AND ts >= ?",
                    (t, (now - timedelta(days=3)).isoformat()),
                ).fetchone()
                if not dup:
                    con.execute(
                        "INSERT INTO verdicts VALUES (?,?,?,?)", (now.isoformat(), t, price, title)
                    )
                    con.commit()
            lines.append(f"- `{t}`: {'; '.join(facts)} → {verdict}")
    return lines


def weekly_due(con, today):
    """True when the weekly block has not rendered for WEEKLY_EVERY_DAYS days.

    Deliberately NOT "Sunday at 18:00". A wall-clock instant only fires if a run
    happens to land on it, and none of the scheduled runs does — which is how the
    project's only zombie-feed detector came to be unreachable rather than merely
    unread. A "has it been N days" marker fires on whichever run comes first, so
    it cannot be missed by a schedule change, a skipped trigger or a red run.
    """
    last = db.flag(con, WEEKLY_FLAG)
    if not last:
        return True
    try:
        return (today - date.fromisoformat(last[:10])).days >= WEEKLY_EVERY_DAYS
    except ValueError:
        return True


def weekly_lines(con, now):
    if not weekly_due(con, now.date()):
        return []
    week_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    n_art, n_sig = con.execute(
        "SELECT COUNT(*), SUM(tickers != '') FROM articles WHERE fetched_at >= ?", (week_ago,)
    ).fetchone()
    lines = [
        "",
        "## 📅 Weekly report",
        "",
        f"- Articles collected this week: **{n_art}** ({n_sig or 0} matched to stocks)",
        "- Scoreboard detail (hit rates vs baseline, verdict outcomes): see "
        "`digests/LATEST.md` in the repo",
    ]
    feeds = json.loads((BASE / "config.json").read_text())["feeds"]
    silent_cutoff = (datetime.now(UTC) - timedelta(hours=FEED_SILENT_HOURS)).isoformat()
    silent = []
    for f in feeds:
        last = con.execute(
            "SELECT MAX(fetched_at) FROM articles WHERE source = ?", (f["name"],)
        ).fetchone()[0]
        if not last or last < silent_cutoff:
            silent.append(f["name"])
    lines.append(
        f"- Feed health: {len(feeds) - len(silent)}/{len(feeds)} sources active"
        + (f" — ⚠️ silent 48h+: {', '.join(silent)}" if silent else "")
    )
    return lines


def main():
    # The bot's book IS the portfolio now — the manual account was retired.
    # Guarded, like bot_recent_trades(): this read used to be a bare
    # json.loads(read_text()) with no .exists() and no decode guard, so a
    # truncated ledger took out two of seven pipeline steps at once.
    ledger = BASE / "bot_portfolio.json"
    if not ledger.exists():
        sys.exit(f"{ledger.name} is missing — run autotrader.py first.")
    try:
        portfolio = json.loads(ledger.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(
            f"{ledger.name} is not valid JSON ({e}). Restore it with: git checkout -- {ledger.name}"
        )
    held, cash = portfolio["positions"], portfolio["cash"]
    bench = BENCHMARK
    sectors = load_sectors()
    now_local = datetime.now()

    # db.connect rather than sqlite3.connect: the weekly marker lives in `meta`,
    # and migrate() is idempotent, so this guarantees both `meta` and `verdicts`
    # exist instead of hand-creating one of them here.
    con = db.connect(BASE / "news.db")
    since = (datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)).isoformat()
    rows = con.execute(
        "SELECT link, source, title, COALESCE(sentiment, 0), COALESCE(noise, 0) "
        "FROM articles WHERE fetched_at >= ?",
        (since,),
    ).fetchall()
    # Per-(headline, company) rows, not articles.tickers. Two reasons: `tickers`
    # lumps headline claims together with passing body-blurb mentions (measured
    # 38.3% excess, n=193 — worse than a coin flip), and article-level VADER is
    # one score stamped on every company named, which is the L1 bug. This section
    # had neither filter, so listicle previews and body-only mentions became
    # graded ✅ verdicts (LESSONS.md L22).
    pairs = {}
    for link, symbol, sent in con.execute(
        "SELECT tk.link, tk.symbol, COALESCE(tk.llm_sent, a.sentiment) "
        "FROM article_tickers tk JOIN articles a ON a.link = tk.link "
        "WHERE tk.in_title = 1 AND COALESCE(a.noise, 0) = 0 "
        "  AND a.fetched_at >= ?",
        (since,),
    ):
        pairs.setdefault(link, {})[symbol] = sent

    holding_items, opportunities, macros = [], [], []
    seen = set()
    for link, source, title, art_sent, noise in rows:
        if title in seen:
            continue
        # Company sections: real news, named in the HEADLINE, scored per pair.
        # Macro is deliberately NOT noise-filtered — "Sensex crashes 1,000
        # points" is correctly flagged noise (it makes no claim about any one
        # company) and is exactly what the macro section exists to surface.
        by_sym = pairs.get(link, {}) if not noise else {}
        tset = {s for s, v in by_sym.items() if v is not None}
        # One score per item is the existing shape. With a single company in the
        # headline — the overwhelming majority — this IS that pair's score. Where
        # a headline names several, take the strongest claim, which is already how
        # the opportunity sort below treats the number.
        sent = max((by_sym[s] for s in tset), key=abs, default=art_sent)
        is_wrap = bool(MARKET_WRAP.search(title))
        if tset & held.keys() and abs(sent) >= HELD_THRESHOLD and not is_wrap:
            held_syms = sorted(tset & held.keys())
            sent = max((by_sym[s] for s in held_syms), key=abs)
            holding_items.append((sent, held_syms, title, source))
        elif tset and abs(sent) >= OPPORTUNITY_THRESHOLD and not is_wrap:
            opportunities.append((sent, sorted(tset), title, source))
        elif MACRO_EVENT.search(title) and MACRO_SCOPE.search(title):
            sent = art_sent
            hit_sectors = set().union(*(secs for pat, secs in EXPOSURE if pat.search(title)))
            touched = sorted(t for t in held if sectors.get(t) in hit_sectors)
            macros.append((sent, touched, title, source))
        else:
            continue
        seen.add(title)

    opportunities.sort(key=lambda i: -abs(i[0]))
    opportunities = opportunities[:MAX_OPPORTUNITIES]
    macros = macros[:MAX_MACRO]

    # Decided BEFORE prices so the weekly gate lives in exactly one place. It used
    # to be duplicated here as a second `weekday()==6 and hour==18` test, which is
    # two chances to get the same unreachable condition wrong.
    weekly_sec = weekly_lines(con, now_local)

    price_symbols = set(held)
    if bench:
        price_symbols.add(bench["symbol"])
    prices = (
        get_prices(price_symbols)
        if (holding_items or opportunities or macros or weekly_sec)
        else {}
    )
    bot_trades, bot = bot_recent_trades()

    if not (holding_items or opportunities or macros or weekly_sec or bot_trades):
        OUT.unlink(missing_ok=True)
        con.close()
        print("No alerts this window.")
        return

    by_ticker = {}
    for sent, tks, title, source in holding_items:
        for t in tks:
            by_ticker.setdefault(t, []).append((sent, title, source))
    n_review = sum(1 for items in by_ticker.values() if sum(s for s, _, _ in items) <= -0.2)

    bits = []
    if n_review:
        bits.append(f"{n_review} holding(s) to REVIEW")
    if len(by_ticker) - n_review:
        bits.append(f"{len(by_ticker) - n_review} holding(s) with good news")
    if opportunities:
        bits.append(f"{len(opportunities)} buy idea(s)")
    if bot_trades:
        bits.append(f"bot made {len(bot_trades)} trade(s)")
    if macros:
        bits.append(f"{len(macros)} macro item(s)")
    if weekly_sec:
        bits.append("weekly report")
    if not bits:
        bits = ["portfolio check"]

    lines = [f"# Stocks {now_local:%d %b %H:%M} IST — " + ", ".join(bits), ""]
    blines, bot_total, shadow = book_lines(held, cash, bench, prices)
    lines.extend(blines)
    lines.extend(bot_lines(bot, bot_trades, bot_total, shadow))

    if by_ticker:
        lines.append("\n## 🧳 News on stocks the BOT owns\n")
        for t in sorted(by_ticker, key=lambda t: sum(s for s, _, _ in by_ticker[t])):
            pos = held[t]
            net = sum(s for s, _, _ in by_ticker[t])
            lines.append(f"### {t} — bot holds {pos['qty']} @ avg Rs {pos['avg_cost']:.2f}")
            for sent, title, source in by_ticker[t]:
                lines.append(f"- {dot(sent)} ({sent:+.2f}) {md(title)} — *{md(source)}*")
            advice = (
                REVIEW_ADVICE if net <= -0.2 else SUPPORT_ADVICE if net >= 0.2 else MIXED_ADVICE
            )
            lines.append(f"\n{advice}\n")

    if opportunities:
        lines.append("\n## 💡 Strong signals on stocks you DON'T own\n")
        for sent, tks, title, source in opportunities:
            lines.append(
                f"- {dot(sent)} ({sent:+.2f}) `{','.join(tks)}` {md(title)} — *{md(source)}*"
            )
        lines.extend(opportunity_checks(opportunities, cash, con, datetime.now(UTC)))
        lines.append(f"\n{OPPORTUNITY_ADVICE}\n")

    if macros:
        lines.append("\n## 🌍 Macro / world events\n")
        for sent, touched, title, source in macros:
            tag = (
                f" → touches your **{', '.join(touched)}**"
                if touched
                else " → no direct hit on your holdings"
            )
            lines.append(f"- {dot(sent)} {md(title)} — *{md(source)}*{tag}")
        lines.append(f"\n{MACRO_ADVICE}\n")

    lines.extend(weekly_sec)
    lines.append(
        "\n---\n_Sentiment is mechanical (word-based); it reads headlines, not "
        "fundamentals. Paper portfolio — verify anything before treating it as "
        "a real-money process._"
    )
    atomic_write_text(OUT, "\n".join(lines))
    # Only after the file exists on disk: a crash between the two would otherwise
    # burn the weekly slot without anyone seeing the report.
    if weekly_sec:
        db.set_flag(con, WEEKLY_FLAG, str(now_local.date()))
    con.close()
    print(f"Alert written: {', '.join(bits)}")


if __name__ == "__main__":
    main()
