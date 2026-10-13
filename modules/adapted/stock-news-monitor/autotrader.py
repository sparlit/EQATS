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


"""Autonomous paper trader (the bot) — trades the NSE universe on its own
analysis with Rs 5000, and learns from measured outcomes.

Run cycle, tied to the actual NSE session (see market_phase):
  pre-open (07:00-09:15 IST)  PLAN  — read the whole overnight news window and
                                      QUEUE intended buys. No fills: while the
                                      market is shut the only available price is
                                      yesterday's close, and buying at it using
                                      news that broke afterwards is look-ahead
                                      bias — flattering on paper, impossible in
                                      real life.
  session  (09:15-15:30 IST)  TRADE — re-check the queued plan against fresh
                                      prices and news, then fill at a price the
                                      bot could actually have got. Exits run on
                                      every session pass so a stop-loss is not
                                      held hostage to the daily cycle — but both
                                      exits and entries are behind
                                      session_data_fresh(), so neither side
                                      transacts on a day the index has no bar
                                      for.
  otherwise                   CLOSED— gather news only. Never transact.

That last rule is not theoretical. Audited 2026-07-30: 36 of this bot's first 41
trades (88%) had executed while the NSE was shut, at closing prices it could
never have obtained — including 13 buys and sells on Sunday 2026-07-26. Every
performance number produced before that date is structurally invalid, not merely
noisy. Do not compare across that boundary.

Learning loops, recomputed every run:
  * source weights - from the `labels` table scoreboard.py maintains (NOT the
    `graded` table, which nothing reads - see db.py / NM-11): sources whose
    signals predict badly lose influence on buy decisions
  * sector weights — experiential: every closed trade nudges its sector up
    (win, x1.05) or down (loss, x0.92); repeated mistakes shrink future bets
  * every closed trade is journaled in bot_portfolio.json -> "closed" with
    entry thesis, exit reason and P&L — the bot's mistake ledger

Buy: score = sentiment x source_weight x sector_weight >= 0.55, plus confirmation
(2+ outlets, 2+ distinct stories, not already up 2.5% today), max 6 positions,
max 20% of equity each, max 2 per sector.
Exits: -7% stop, +15% target, 15-day time stop, or strong negative news.
"""
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib

from alerts import load_sectors
from newslib import IST, atomic_write_text, distinct_stories, is_trading_day
from paper_portfolio import FEES_PCT, live_price

BASE = Path(__file__).parent
LEDGER = BASE / "bot_portfolio.json"
START_CASH = 5000.0

# NSE continuous session, in minutes past IST midnight.
SESSION_OPEN_MIN = 9 * 60 + 15
SESSION_CLOSE_MIN = 15 * 60 + 30
PLAN_FROM_MIN = 7 * 60  # earliest pre-open run that may queue a plan

# Reach back past the previous close so the pre-open scan sees the whole
# overnight window (15:30 yesterday -> 09:15 today), including US-session news.
CANDIDATE_HOURS = 18
MIN_SENT = 0.5
BUY_SCORE = 0.55
STOP_PCT, TARGET_PCT, MAX_HOLD_DAYS = -7.0, 15.0, 15
MAX_POSITIONS, POSITION_FRAC, SECTOR_MAX = 6, 0.20, 2
PRICED_IN_MOVE = 2.5
REBUY_COOLDOWN_DAYS = 3
CANCEL_ON_NEWS = -0.5  # queued buy is dropped if sentiment turns this negative


FRESH_LEDGER = {
    "cash": START_CASH,
    "positions": {},
    "trades": [],
    "closed": [],
    "sector_weights": {},
    "pending": [],
}


def load():
    """The ledger, or a fresh book if there is none.

    A corrupt ledger must NOT be silently replaced by a fresh Rs 5,000 book —
    that would erase the track record and print a fake +0.00%. Fail loudly
    instead; the file is in git, so recovery is a checkout.
    """
    if not LEDGER.exists():
        return dict(FRESH_LEDGER)
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(
            f"{LEDGER.name} is not valid JSON ({e}). Refusing to start from "
            "a blank book — that would erase the track record. Restore it "
            f"with: git checkout -- {LEDGER.name}"
        )


def save(p):
    # Atomic: a truncated ledger would be committed by the workflow's
    # `if: always()` step and break every later run (NM-22 / LESSONS.md L22).
    atomic_write_text(LEDGER, json.dumps(p, indent=2))


def market_phase(ist_now):
    """'plan' | 'trade' | 'closed' — what this run is permitted to do.

    Checks the NSE holiday calendar, not just the weekday. Republic Day, Holi,
    Gandhi Jayanti and Christmas all fall on weekdays in 2026; without this the
    bot would decide the market was open and fill at a stale close on ~10 days a
    year — the L5 bug returning through the back door.
    """
    if not is_trading_day(ist_now.date()):
        return "closed"
    mins = ist_now.hour * 60 + ist_now.minute
    if PLAN_FROM_MIN <= mins < SESSION_OPEN_MIN:
        return "plan"
    if SESSION_OPEN_MIN <= mins <= SESSION_CLOSE_MIN:
        return "trade"
    return "closed"


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


def worst_news(con, sym, since):
    """Most negative per-ticker score for a symbol since `since` (None if silent)."""
    return con.execute(
        "SELECT MIN(COALESCE(t.llm_sent, a.sentiment)) "
        "FROM article_tickers t JOIN articles a ON a.link = t.link "
        "WHERE t.symbol = ? AND t.in_title = 1 "
        "AND COALESCE(a.noise, 0) = 0 AND a.fetched_at >= ?",
        (sym, since),
    ).fetchone()[0]


def confirmed(con, sym, since):
    """True when 2+ outlets carried 2+ genuinely distinct stories on this name.

    Confirmation must come from real news: counting tracker pages and listicle
    previews as "independent coverage" is how a single wire reprint used to pass
    as two outlets agreeing.
    """
    cov = con.execute(
        "SELECT a.source, a.title FROM article_tickers t "
        "JOIN articles a ON a.link = t.link "
        "WHERE t.symbol = ? AND t.in_title = 1 AND COALESCE(a.noise, 0) = 0 "
        "AND a.fetched_at >= ? AND ABS(COALESCE(t.llm_sent, a.sentiment)) >= 0.25",
        (sym, since),
    ).fetchall()
    return len({s for s, _ in cov}) >= 2 and distinct_stories([t for _, t in cov]) >= 2


def session_data_fresh(today_ist):
    """True when the index actually has a bar for today.

    Belt-and-braces behind the holiday list, which is hand-maintained and will
    eventually go stale (unscheduled closures, or the 2027 list being provisional
    until NSE publishes its circular). On a shut day the newest bar is the
    previous session's, so this catches a missing holiday without needing to know
    about it.

    Gates BOTH sides of the book. It used to gate entries only, which left exits
    filling at a stale close on any day the calendar got wrong — the L5 bug
    surviving on the sell side. Failing this only DELAYS the day: pending orders
    are left intact, no position is closed, and the next hourly run retries. So a
    slow Yahoo update costs an hour, and a genuine closure costs the day.
    """
    try:
        import yfinance as yf

        idx = yf.Ticker("^NSEI").history(period="5d")["Close"].dropna()
        if not len(idx):
            return False
        return idx.index[-1].date() == today_ist
    except Exception:
        return False


def quote(sym):
    """(price, % move today) from real bars, or (None, None)."""
    try:
        import yfinance as yf

        closes = yf.Ticker(sym).history(period="2d")["Close"].dropna()
        if not len(closes):
            return None, None
        price = float(closes.iloc[-1])
        move = (price / float(closes.iloc[-2]) - 1) * 100 if len(closes) >= 2 else 0.0
        return price, move
    except Exception:
        return None, None


def close_position(p, sym, price, reason, sectors, now_iso):
    pos = p["positions"].pop(sym)
    proceeds = price * pos["qty"]
    fee = proceeds * FEES_PCT
    p["cash"] += proceeds - fee
    pnl_pct = (price / pos["avg_cost"] - 1) * 100
    win = pnl_pct > 0
    sec = sectors.get(sym, "")
    w = p["sector_weights"].get(sec, 1.0)
    p["sector_weights"][sec] = round(max(0.5, min(1.3, w * (1.05 if win else 0.92))), 3)
    p["trades"].append(
        {
            "time": now_iso,
            "action": "sell",
            "symbol": sym,
            "qty": pos["qty"],
            "price": round(price, 2),
            "fee": round(fee, 2),
            "reason": reason,
        }
    )
    p["closed"].append(
        {
            "time": now_iso,
            "symbol": sym,
            "sector": sec,
            "entry": round(pos["avg_cost"], 2),
            "exit": round(price, 2),
            "pnl_pct": round(pnl_pct, 2),
            "win": win,
            "reason": reason,
            "thesis": pos.get("thesis", ""),
        }
    )
    print(f"BOT SOLD {pos['qty']} x {sym} @ Rs {price:.2f} ({pnl_pct:+.2f}%) — {reason}")


def check_exits(p, con, sectors, prices, now, now_iso, since):
    """Stop / target / time / news exits.

    Session-time only, AND only when session_data_fresh() says the index has a bar
    for today — a sell needs a price the bot could actually have hit. The caller
    owns that gate; do not call this without it.
    """
    for sym, pos in list(p["positions"].items()):
        price = prices.get(sym)
        if not price:
            continue
        pct = (price / pos["avg_cost"] - 1) * 100
        held_days = (now - datetime.fromisoformat(pos["opened"])).days
        worst = worst_news(con, sym, since)
        if pct <= STOP_PCT:
            close_position(p, sym, price, f"stop-loss at {pct:+.1f}%", sectors, now_iso)
        elif pct >= TARGET_PCT:
            close_position(p, sym, price, f"target hit at {pct:+.1f}%", sectors, now_iso)
        elif held_days >= MAX_HOLD_DAYS:
            close_position(
                p, sym, price, f"time stop after {held_days}d ({pct:+.1f}%)", sectors, now_iso
            )
        elif worst is not None and worst <= -0.5:
            close_position(
                p, sym, price, f"negative news ({worst:+.2f}) at {pct:+.1f}%", sectors, now_iso
            )


def plan_orders(p, con, sw, sectors, now, since, day):
    """Pre-open: rank the overnight news and queue intended buys.

    Uses per-(headline, company) rows, not article-level sentiment. The old query
    stamped one score on every company an article named, so "Elara Securities
    prefers ICICI Bank over HDFC Bank" was a BUY signal for HDFC Bank. Noise rows
    and body-only mentions are excluded — both measured anti-predictive
    2026-07-30.
    """
    arts = con.execute(
        "SELECT a.source, a.title, COALESCE(t.llm_sent, a.sentiment) AS sent, "
        "       t.symbol "
        "FROM article_tickers t JOIN articles a ON a.link = t.link "
        "WHERE t.in_title = 1 AND COALESCE(a.noise, 0) = 0 "
        "  AND COALESCE(t.llm_sent, a.sentiment) >= ? AND a.fetched_at >= ?",
        (MIN_SENT, since),
    ).fetchall()
    cooldown = (now - timedelta(days=REBUY_COOLDOWN_DAYS)).isoformat()
    cand = {}
    for source, title, sent, sym in arts:
        if sym in p["positions"]:
            continue
        if any(t["symbol"] == sym and t["time"] >= cooldown for t in p["trades"]):
            continue
        score = sent * sw.get(source, 1.0) * p["sector_weights"].get(sectors.get(sym, ""), 1.0)
        if score >= BUY_SCORE and (sym not in cand or score > cand[sym][0]):
            cand[sym] = (score, title, source)

    plan, slots = [], MAX_POSITIONS - len(p["positions"])
    sector_count = {}
    for s in p["positions"]:
        sec = sectors.get(s, "")
        sector_count[sec] = sector_count.get(sec, 0) + 1
    for sym, (score, title, source) in sorted(cand.items(), key=lambda kv: -kv[1][0]):
        if len(plan) >= slots:
            break
        sec = sectors.get(sym, "")
        if sector_count.get(sec, 0) >= SECTOR_MAX:
            continue
        if not confirmed(con, sym, (now - timedelta(hours=24)).isoformat()):
            continue
        sector_count[sec] = sector_count.get(sec, 0) + 1
        plan.append(
            {
                "symbol": sym,
                "score": round(score, 3),
                "title": title[:100],
                "source": source,
                "queued": day,
            }
        )
    return plan


def execute_pending(p, con, sectors, prices, now, now_iso, since):
    """At the open: re-validate each queued order, then fill at a live price.

    The re-check is the point of splitting plan from execution — overnight news
    can be undone by the opening print. A name that gapped up on the very news
    that selected it has already paid out, and a name whose story turned negative
    overnight should never be bought.
    """
    for order in p.get("pending", []):
        sym = order["symbol"]
        if sym in p["positions"] or len(p["positions"]) >= MAX_POSITIONS:
            continue
        worst = worst_news(con, sym, since)
        if worst is not None and worst <= CANCEL_ON_NEWS:
            print(f"CANCELLED {sym} — news turned negative overnight ({worst:+.2f})")
            continue
        if not confirmed(con, sym, (now - timedelta(hours=24)).isoformat()):
            print(f"CANCELLED {sym} — coverage no longer independently confirmed")
            continue
        price, move = quote(sym)
        if price is None:
            print(f"CANCELLED {sym} — no price available at the open")
            continue
        if move is not None and move >= PRICED_IN_MOVE:
            print(f"CANCELLED {sym} — gapped {move:+.1f}%, the news is already priced in")
            continue
        eq = p["cash"] + sum(
            prices.get(s, pos["avg_cost"]) * pos["qty"] for s, pos in p["positions"].items()
        )
        budget = min(p["cash"], eq * POSITION_FRAC)
        qty = int(budget // (price * (1 + FEES_PCT)))
        if qty < 1:
            print(f"CANCELLED {sym} — 1 share (Rs {price:,.2f}) exceeds the sizing cap")
            continue
        cost = price * qty
        fee = cost * FEES_PCT
        p["cash"] -= cost + fee
        p["positions"][sym] = {
            "qty": qty,
            "avg_cost": (cost + fee) / qty,
            "opened": now_iso,
            "sources": [order["source"]],
            "thesis": order["title"],
        }
        p["trades"].append(
            {
                "time": now_iso,
                "action": "buy",
                "symbol": sym,
                "qty": qty,
                "price": round(price, 2),
                "fee": round(fee, 2),
                "reason": f"planned pre-open, score {order['score']:.2f} "
                f"({order['source']}): {order['title'][:70]}",
            }
        )
        prices[sym] = price
        print(
            f"BOT BOUGHT {qty} x {sym} @ Rs {price:.2f} "
            f"(planned score {order['score']:.2f}) — {order['title'][:65]}"
        )


def print_status(p, prices, sw):
    total = p["cash"] + sum(
        prices.get(s, pos["avg_cost"]) * pos["qty"] for s, pos in p["positions"].items()
    )
    print(
        f"\nBot equity: Rs {total:,.2f} ({100 * (total - START_CASH) / START_CASH:+.2f}% "
        f"since start) — cash Rs {p['cash']:,.2f}, {len(p['positions'])} position(s)"
    )
    for s, pos in p["positions"].items():
        pr = prices.get(s, pos["avg_cost"])
        print(
            f"  {s:<15} {pos['qty']:>3} @ {pos['avg_cost']:.2f} -> {pr:.2f} "
            f"({100 * (pr / pos['avg_cost'] - 1):+.2f}%)"
        )
    closed = p["closed"]
    if closed:
        wins = sum(1 for c in closed if c["win"])
        print(
            f"Record: {wins}/{len(closed)} wins, "
            f"avg {sum(c['pnl_pct'] for c in closed) / len(closed):+.2f}% per trade"
        )
    if sw:
        ranked = sorted(sw.items(), key=lambda kv: -kv[1])
        print("Learned source trust — high:", ", ".join(f"{s} {w:.2f}" for s, w in ranked[:3]))
        print("                       low:", ", ".join(f"{s} {w:.2f}" for s, w in ranked[-3:]))
    if p["sector_weights"]:
        print("Learned sector weights:", json.dumps(p["sector_weights"]))


def main():
    p = load()
    p.setdefault("pending", [])
    sectors = load_sectors()
    con = sqlite3.connect(BASE / "news.db")
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    ist_now = now.astimezone(IST)
    day = str(ist_now.date())
    phase = market_phase(ist_now)
    sw = source_weights(con)
    since = (now - timedelta(hours=CANDIDATE_HOURS)).isoformat()

    # Prices are always fetched for REPORTING; only the trade phase may act on
    # them. Reading a stale close is fine, transacting at one is not.
    prices = {}
    for sym in list(p["positions"]):
        with contextlib.suppress(Exception, SystemExit):
            prices[sym] = live_price(sym)

    if phase == "closed":
        print(
            f"NSE shut ({ist_now:%a %d %b %H:%M} IST) — news gathering only, "
            "no trades. Prices below are the last close."
        )
        if p["pending"] and p["pending"][0]["queued"] != day:
            print(
                f"  (dropping {len(p['pending'])} stale order(s) queued "
                f"{p['pending'][0]['queued']} that never reached an open)"
            )
            p["pending"] = []
            save(p)

    elif phase == "plan":
        p["pending"] = plan_orders(p, con, sw, sectors, now, since, day)
        save(p)
        if p["pending"]:
            print(
                f"PLANNED for the {ist_now:%d %b} open — {len(p['pending'])} order(s), "
                "each re-checked against fresh prices and news before filling:"
            )
            for o in p["pending"]:
                print(f"  QUEUE BUY {o['symbol']:<15} score {o['score']:.2f} — {o['title'][:60]}")
        else:
            print("Pre-open scan: no candidate cleared the bar in the overnight news.")

    else:  # trade
        # ONE data-derived freshness check for the whole trade phase. This used
        # to gate entries only, so check_exits ran unconditionally: on a holiday
        # missing from NSE_HOLIDAYS the calendar said "open", live_price()
        # returned the PREVIOUS close, and a position sitting below the stop
        # against that stale close was "sold" at a price that never existed.
        # That is LESSONS.md L5's impossible fill on the sell side, and it is
        # worse than the buy side: it books a realised P&L into the closed-trade
        # record and nudges a learned sector weight off a fill that never
        # happened. A sell needs a price the bot could actually have hit, which
        # is exactly what this check tests.
        fresh = session_data_fresh(ist_now.date())
        if fresh:
            check_exits(p, con, sectors, prices, now, now_iso, since)
        else:
            print(
                f"NO index bar for {day} — the market may be shut (unlisted "
                "holiday) or the feed is lagging. NEITHER exits nor entries "
                "run this pass; the plan is kept for the next one. Prices "
                "below are the last close."
            )
        if p["pending"] and p["pending"][0]["queued"] == day:
            if p.get("traded_day") == day:
                print("Plan already executed today — holding.")
            elif fresh:
                execute_pending(p, con, sectors, prices, now, now_iso, since)
                p["traded_day"] = day
                p["pending"] = []
        elif p["pending"]:
            # Dropping a stale plan is bookkeeping, not a trade, so it does not
            # need fresh data.
            print(
                f"Dropping {len(p['pending'])} order(s) queued "
                f"{p['pending'][0]['queued']} — a plan is only good for its own open."
            )
            p["pending"] = []
        elif fresh and p.get("traded_day") != day:
            print(
                "No pre-open plan for today — no entries. "
                "(Entries are queued by the 08:15 run; exits still run.)"
            )
        elif fresh:
            print("Today's plan is already done — exits checked, holding.")
        save(p)

    print_status(p, prices, sw)
    con.close()


if __name__ == "__main__":
    main()
