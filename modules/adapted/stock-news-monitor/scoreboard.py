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


"""Grade past news signals against what stocks actually did.

Grades one row per (article, company) pair — never a whole article — and only
real news (tracker pages, listicles and index wraps are excluded via the noise
flag; they used to be ~24% of all signals and, being backward-looking
descriptions of moves that had already happened, they INFLATED the hit rate).

Two hit rates are reported, and the second one is the honest one:
  * RAW direction   — did the stock go up after positive news? Compared against
                      the always-bull baseline, because the market drifts up.
  * EXCESS vs NIFTY — did the stock beat the index? Market drift cancels out, so
                      the baseline is a clean 50%. This is the number that has to
                      clear its confidence interval before any edge is real.

Splits the result by the things most likely to carry edge (ROADMAP_ML.md §5):
after-hours vs in-session, novel vs descriptive, headline vs body mention.

Also writes the `labels` table — the growing ML dataset. See ROADMAP_ML.md §1.

Usage: python scoreboard.py
"""
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import db
from newslib import cluster_titles, signal_trading_day

BASE = Path(__file__).parent
DB = BASE / "news.db"
THRESHOLD = 0.25  # |sentiment| below this is neutral -> not a directional signal
HORIZONS = (1, 3, 5)
WINDOW_DAYS = 30
SHOW_ROWS = 15
BENCHMARK = "^NSEI"  # NIFTY 50, for excess-return grading

# The scoreboard prints several EDGE? tests at once (horizons x splits). At 95%
# each, running 9 of them gives a ~37% chance that one clears by luck alone —
# and we are hunting a small edge, so a false positive would be believed.
# Confidence intervals are Bonferroni-widened by this count.
N_TESTS = 9
PRIMARY_HYPOTHESIS = ("after-hours", 1)  # the ONE pre-registered test (§5 roadmap)

# Every `labels` column this script writes. n_sources is NOT here and must never
# be added back: its values are frozen at their old (leaky, un-windowed) meaning
# so the column has ONE definition throughout its history instead of two silently
# mixed ones. n_sources_win replaces it. ROADMAP_ML §3: P1 uses n_sources_win.
_LABEL_COLS = (
    "link",
    "symbol",
    "day",
    "source",
    "title",
    "vader",
    "llm_sent",
    "llm_novel",
    "in_title",
    "after_hours",
    "n_sources_win",
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "mkt_1d",
    "mkt_3d",
    "mkt_5d",
)
LABEL_UPSERT = (
    f"INSERT INTO labels ({', '.join(_LABEL_COLS)}) "
    f"VALUES ({','.join('?' * len(_LABEL_COLS))}) "
    f"ON CONFLICT(link, symbol) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _LABEL_COLS[2:])
)
LABELS_SCHEMA_NOTE = (
    "n_sources frozen 2026-07-30 (un-windowed lifetime coverage, "
    "leaks future news into old rows); n_sources_win added "
    "(independent stories in [day-1, day+1]) — P1 uses n_sources_win"
)

_price_cache = {}


def closes_for(symbol):
    if symbol not in _price_cache:
        try:
            hist = yf.Ticker(symbol).history(period="6mo")
        except Exception as e:
            # "the request failed" and "this symbol has no rows" are different
            # problems with the same None; say which one happened.
            print(f"  price fetch FAILED for {symbol}: {type(e).__name__}")
            hist = None
        if hist is None:
            _price_cache[symbol] = None
        elif hist.empty:
            print(f"  price fetch returned NO ROWS for {symbol}")
            _price_cache[symbol] = None
        else:
            hist.index = hist.index.tz_localize(None)
            # yfinance emits NaN closes for partial/placeholder bars (a run before
            # the session ends returns one for today). Any NaN that survives into
            # a return calculation silently poisons the whole scoreboard.
            _price_cache[symbol] = hist["Close"].dropna()
    return _price_cache[symbol]


def horizon_returns(symbol, date):
    """% returns from the close on/before `date` to 1/3/5 trading closes after."""
    closes = closes_for(symbol)
    if closes is None:
        return {}
    day_end = datetime.combine(date, datetime.max.time())
    before = closes[closes.index <= day_end]
    after = closes[closes.index > day_end]
    if len(before) < 1:
        return {}
    base = float(before.iloc[-1])
    return {h: (float(after.iloc[h - 1]) / base - 1) * 100 for h in HORIZONS if len(after) >= h}


def ci95(p, n, tests=N_TESTS):
    """Bonferroni-corrected confidence half-width, in percentage points.

    z is raised from 1.96 to the two-sided quantile for alpha/tests, so a table
    of nine simultaneous tests cannot manufacture an EDGE? by chance.
    """
    if not n:
        return 0.0
    z = _norm_ppf(1 - (0.05 / max(tests, 1)) / 2)
    return z * math.sqrt(p * (1 - p) / n) * 100


def _norm_ppf(q):
    """Inverse normal CDF (Acklam's approximation) — avoids a scipy dependency."""
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p_low = 0.02425
    if q < p_low:
        x = math.sqrt(-2 * math.log(q))
        return (((((c[0] * x + c[1]) * x + c[2]) * x + c[3]) * x + c[4]) * x + c[5]) / (
            (((d[0] * x + d[1]) * x + d[2]) * x + d[3]) * x + 1
        )
    if q > 1 - p_low:
        x = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0] * x + c[1]) * x + c[2]) * x + c[3]) * x + c[4]) * x + c[5]) / (
            (((d[0] * x + d[1]) * x + d[2]) * x + d[3]) * x + 1
        )
    x = q - 0.5
    r = x * x
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * x
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def rate_line(label, sample):
    """sample: [(hit, excess_hit)] -> one formatted row, or None if empty."""
    n = len(sample)
    if not n:
        return None
    raw = 100 * sum(1 for h, _ in sample if h) / n
    exc = 100 * sum(1 for _, e in sample if e) / n
    ci = ci95(exc / 100, n)
    return (
        f"{label:<22}{n:>6}{raw:>8.1f}{exc:>9.1f}{ci:>7.1f}"
        f"{'EDGE?' if exc - ci > 50 else 'no edge':>10}"
    )


def main():
    con = db.connect(DB)
    now = datetime.now(UTC)

    # One flaky Yahoo request used to be indistinguishable from a flat market:
    # closes_for caches None for the whole process, every mkt lookup returns {},
    # and `excess = ret - mkt.get(h, 0.0)` quietly re-becomes raw direction — the
    # drift-inflated number this project abandoned on purpose (LESSONS.md L9),
    # printed under an "excess%" heading with the same EDGE? verdict logic.
    # Worse, the run still wrote `labels` with INSERT OR REPLACE, overwriting 30
    # days of correct mkt_1d/3d/5d with NULL. `labels` is the asset the whole ML
    # roadmap is gated on, so a benchmark outage must stop the run BEFORE any
    # write, not degrade quietly. Going red here is intended: it opens an issue.
    if closes_for(BENCHMARK) is None:
        print(
            f"[FAILED] benchmark {BENCHMARK} unavailable — labels NOT written "
            "this run and no hit rates published. Excess-vs-NIFTY cannot be "
            "computed, and raw direction is not a substitute for it."
        )
        con.close()
        sys.exit(1)

    rows = con.execute(
        "SELECT t.link, t.symbol, a.title, a.source, a.sentiment, t.llm_sent, "
        "       t.llm_novel, t.in_title, a.after_hours, "
        "       COALESCE(a.published, a.fetched_at) "
        "FROM article_tickers t JOIN articles a ON a.link = t.link "
        "WHERE COALESCE(a.noise, 0) = 0 "
        "  AND COALESCE(a.published, a.fetched_at) < ? "
        "  AND COALESCE(a.published, a.fetched_at) >= ?",
        ((now - timedelta(days=1)).isoformat(), (now - timedelta(days=WINDOW_DAYS)).isoformat()),
    ).fetchall()

    samples = {h: [] for h in HORIZONS}
    by_hours, by_novel, by_where = {}, {}, {}
    detail, by_source, label_rows, graded_rows = [], {}, [], []

    # How much independent coverage this company got AROUND the signal, within
    # [day-1, day+1] (ML feature). The old version had no date bound at all: it
    # was per-symbol LIFETIME coverage — a company-size proxy, not per-story
    # independence — and because every in-window row is rewritten each run, the
    # value stored on an old row kept growing with news published after it. That
    # is future leakage into a feature ROADMAP_ML §3 lists as P1, in a dataset
    # whose stated evaluation protocol is walk-forward. Values reached 72 for a
    # 4-week corpus, which is what gave it away. It is written to the NEW column
    # n_sources_win; n_sources is frozen, never rewritten. The date bound also
    # bounds the O(n^2) title clustering, which had no bound either.
    titles_by_day = {}
    for symbol, ts, title in con.execute(
        "SELECT t.symbol, COALESCE(a.published, a.fetched_at), a.title "
        "FROM article_tickers t JOIN articles a ON a.link = t.link "
        "WHERE COALESCE(a.noise, 0) = 0"
    ).fetchall():
        if ts:
            titles_by_day.setdefault(symbol, {}).setdefault(ts[:10], []).append(title)

    win_cache = {}

    def coverage_window(symbol, day):
        """Independent stories about `symbol` published in [day-1, day+1]."""
        if (symbol, day) not in win_cache:
            by_day = titles_by_day.get(symbol, {})
            titles = []
            for delta in (-1, 0, 1):
                titles += by_day.get((day + timedelta(days=delta)).isoformat(), [])
            win_cache[(symbol, day)] = len(set(cluster_titles(titles)))
        return win_cache[(symbol, day)]

    for link, symbol, title, source, vader, llm, novel, in_title, after_hours, ts in rows:
        sent = llm if llm is not None else vader
        # Trading day, NOT the calendar date: news at 02:00 IST belongs to the
        # PREVIOUS session's close, otherwise the overnight gap — the exact move
        # an after-hours signal is meant to capture — is measured away.
        date = signal_trading_day(ts)
        if date is None:
            continue
        rets = horizon_returns(symbol, date)
        mkt = horizon_returns(BENCHMARK, date)
        if not rets:
            continue
        # The ML dataset keeps EVERY pair, including neutral ones. A classifier
        # trained only on directional signals can never learn to recognise a
        # weak one, because it never sees "looks like news, isn't tradeable".
        label_rows.append(
            (
                link,
                symbol,
                str(date),
                source,
                title,
                vader,
                llm,
                novel,
                in_title,
                after_hours,
                coverage_window(symbol, date),
                rets.get(1),
                rets.get(3),
                rets.get(5),
                mkt.get(1),
                mkt.get(3),
                mkt.get(5),
            )
        )
        if sent is None or abs(sent) < THRESHOLD:
            continue
        up = sent > 0
        for h, ret in rets.items():
            excess = ret - mkt.get(h, 0.0)
            pair = ((up == (ret > 0)), (up == (excess > 0)))
            samples[h].append(pair)
            if h == 1:
                by_hours.setdefault("after-hours" if after_hours else "in-session", []).append(pair)
                if novel is not None:
                    by_novel.setdefault("novel" if novel else "descriptive", []).append(pair)
                by_where.setdefault("headline" if in_title else "body mention", []).append(pair)
        if 1 in rets:
            hit = up == (rets[1] > 0)
            detail.append((date, symbol, sent, rets[1], hit, title[:55], source))
            by_source.setdefault(source, []).append(hit)
            graded_rows.append((str(date), symbol, source, title, sent, rets[1], int(hit)))

    # `graded` powers learned source trust in autotrader.py / export_signal.py
    for r in graded_rows:
        con.execute("INSERT OR REPLACE INTO graded VALUES (?,?,?,?,?,?,?)", r)
    # `labels` is the ML dataset (ROADMAP_ML.md). Written with an UPSERT that
    # names its columns, NOT `INSERT OR REPLACE ... VALUES (17 ?)`: replace is a
    # delete-then-insert, so any column left out of the list would be blanked.
    # n_sources is deliberately left out AND must stay untouched — see
    # meta['labels_schema'].
    for r in label_rows:
        con.execute(LABEL_UPSERT, r)
    db.set_flag(con, "labels_schema", LABELS_SCHEMA_NOTE)
    con.commit()

    if not detail:
        print("No scoreable signals yet — keep collecting.")
    else:
        print(f"=== Recent signals (last {SHOW_ROWS} of {len(detail)}, 1-day horizon) ===")
        print(f"{'date':<12}{'symbol':<15}{'sent':>6}{'move%':>8}  hit  headline")
        for date, symbol, sent, ret, hit, title, _ in sorted(detail)[-SHOW_ROWS:]:
            print(
                f"{date!s:<12}{symbol:<15}{sent:>+6.2f}{ret:>+8.2f}  "
                f"{'YES' if hit else 'no ':<3}  {title}"
            )

        print("\n=== Hit rate by horizon ===")
        print(f"{'horizon':<22}{'n':>6}{'raw%':>8}{'excess%':>9}{'±95%':>7}{'verdict':>10}")
        for h in HORIZONS:
            line = rate_line(f"{h}d", samples[h])
            if line:
                print(line)
        print("  raw%   = direction correct (inflated by market drift)")
        print("  excess% = beat NIFTY over the same window — baseline is a clean 50%")
        print(f"  ±95% is Bonferroni-widened for {N_TESTS} simultaneous tests: at plain")
        print("  95% there is a ~37% chance one row clears 50% by luck alone.")
        print(
            f"  PRE-REGISTERED hypothesis = '{PRIMARY_HYPOTHESIS[0]}' at "
            f"{PRIMARY_HYPOTHESIS[1]}d. Treat every other row as exploratory."
        )

        for name, groups in (
            ("after-hours vs in-session", by_hours),
            ("novel vs descriptive", by_novel),
            ("headline vs body mention", by_where),
        ):
            if len(groups) < 1:
                continue
            print(f"\n=== 1-day split: {name} ===")
            print(f"{'group':<22}{'n':>6}{'raw%':>8}{'excess%':>9}{'±95%':>7}{'verdict':>10}")
            for label, sample in sorted(groups.items()):
                line = rate_line(label, sample)
                if line:
                    print(line)

        print("\n=== By source (1-day, raw direction) ===")
        for source, flags in sorted(by_source.items(), key=lambda kv: -len(kv[1]))[:10]:
            print(
                f"  {source:<30} {sum(flags)}/{len(flags)} ({100 * sum(flags) / len(flags):.0f}%)"
            )

    # head-to-head: VADER vs the per-ticker LLM score, same pairs, 1-day
    #
    # Uses signal_trading_day, like the main grading loop 90 lines above. This
    # block was missed when that loop was migrated (L12), so it kept grading on
    # the raw UTC calendar date — the basis that put 28.5% of pairs against the
    # WRONG SESSION. Anything published after 18:30 IST carries the next UTC
    # date, and weekend/holiday news has no session at all. The 66%-vs-61%
    # figure once quoted in ROADMAP_ML.md came out of here on the old basis and
    # should not be trusted. It also used fromisoformat directly, so a single
    # malformed timestamp raised ValueError and killed the whole scoreboard
    # step; signal_trading_day returns None instead.
    stats = {"VADER": [0, 0], "LLM": [0, 0]}
    for _, symbol, _, _, vader, llm, _, _, _, ts in rows:
        if llm is None:
            continue
        date = signal_trading_day(ts)
        if date is None:
            continue
        rets = horizon_returns(symbol, date)
        if 1 not in rets:
            continue
        up = rets[1] > 0
        if vader is not None and abs(vader) >= THRESHOLD:
            stats["VADER"][0] += (vader > 0) == up
            stats["VADER"][1] += 1
        if abs(llm) >= THRESHOLD:
            stats["LLM"][0] += (llm > 0) == up
            stats["LLM"][1] += 1
    if stats["LLM"][1]:
        print("\n=== VADER vs LLM analyst (same pairs, 1-day) ===")
        for name, (hits, n) in stats.items():
            if n:
                print(f"  {name:<6} {hits}/{n} ({100 * hits / n:.0f}%)")

    n_labels = con.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    print(
        f"\nML dataset: {n_labels} labelled (article, company) rows "
        f"— see ROADMAP_ML.md for the phase gates."
    )

    # grade the ✅ PASSES verdicts from alerts.py at 5 trading days
    verdicts = con.execute(
        "SELECT ts, symbol, price, title FROM verdicts WHERE ts < ?",
        ((now - timedelta(days=1)).isoformat(),),
    ).fetchall()
    if verdicts:
        print("\n=== ✅ verdict journal (5-day outcomes) ===")
        outcomes = []
        for ts, symbol, price, title in verdicts:
            closes = closes_for(symbol)
            if closes is None or not price:
                continue
            day_end = datetime.combine(datetime.fromisoformat(ts).date(), datetime.max.time())
            after = closes[closes.index > day_end]
            if len(after) < 1:
                continue
            ret = (float(after.iloc[min(5, len(after)) - 1]) / price - 1) * 100
            outcomes.append(ret)
            print(f"  {ts[:10]}  {symbol:<15}{ret:>+7.2f}%  {title[:50]}")
        if outcomes:
            wins = sum(1 for r in outcomes if r > 0)
            print(f"  → {wins}/{len(outcomes)} positive, avg {sum(outcomes) / len(outcomes):+.2f}%")
    con.close()


if __name__ == "__main__":
    main()
