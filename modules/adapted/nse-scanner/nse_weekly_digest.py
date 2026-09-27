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
nse_weekly_digest.py — Weekly Performance Digest
==================================================
Always shows LAST COMPLETED week (Mon-Fri).
Called via /digest command or manually.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from telegram_dashboard import dashboard_keyboard

try:
    import config
except ImportError:
    print("ERROR: config.py")
    sys.exit(1)

try:
    from nse_telegram_handler import (
        HISTORY_FILE,
        _b,
        _code,
        _fmt_price,
        _fmt_return,
        _h,
        _i,
        load_history,
    )
except ImportError:

    def _h(v):
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _b(v):
        return f"<b>{_h(v)}</b>"

    def _i(v):
        return f"<i>{_h(v)}</i>"

    def _code(v):
        return f"<code>{_h(v)}</code>"

    def _fmt_price(p):
        return f"\u20b9{round(float(p)):,}"

    def _fmt_return(pct):
        sign = "+" if float(pct) >= 0 else ""
        return f"{sign}{float(pct):.1f}%"

    def load_history():
        return []


os.makedirs(getattr(config, "LOG_DIR", "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(getattr(config, "LOG_DIR", "logs"), "weekly_digest.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

SEP_BOLD = "\u2501" * 17
SEP_THIN = "\u2500" * 18


def _link(symbol):
    safe = _h(symbol)
    return f'<a href="https://www.tradingview.com/chart/?symbol=NSE%3A{safe}">{safe}</a>'


def _fmt_pl(entry, current):
    entry = float(entry)
    current = float(current)
    if entry <= 0:
        return "N/A"
    d = current - entry
    p = d / entry * 100
    s = "+" if d >= 0 else ""
    return f"{s}{p:.1f}%"


def get_week_dates(week_ending=None):
    if week_ending is None:
        week_ending = date.today()
    d = week_ending
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    friday = d
    monday = friday - timedelta(days=friday.weekday())
    dates = []
    cur = monday
    while cur <= friday:
        if cur.weekday() < 5:
            dates.append(cur)
        cur += timedelta(days=1)
    return dates


def get_week_history(history, week_dates):
    ws = {str(d) for d in week_dates}
    wh = [h for h in history if h["date"] in ws]
    wh.sort(key=lambda x: x["date"], reverse=True)
    return wh


def get_week_prices(symbols, week_dates, conn):
    if not week_dates:
        return {}
    sd = min(week_dates)
    ed = max(week_dates)
    results = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT date,open,high,low,close FROM daily_prices WHERE symbol=? AND date>=? AND date<=? ORDER BY date",
            [sym, sd.isoformat(), ed.isoformat()],
        ).fetchall()
        if not rows:
            continue
        mc = float(rows[0][4])
        fc = float(rows[-1][4])
        wh = max(float(r[2]) for r in rows)
        wl = min(float(r[3]) for r in rows)
        wr = (fc - mc) / mc * 100 if mc > 0 else 0
        results[sym] = {
            "monday_close": mc,
            "friday_close": fc,
            "week_high": wh,
            "week_low": wl,
            "week_return_pct": round(wr, 1),
        }
    return results


def _as_date(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def get_confirmed_model_trades(week_history, week_dates, conn):
    """Evaluate only EOD BUY_TRIGGER setups that actually traded through trigger.

    A signal issued after a market close can be filled only on a later session,
    up to its two-business-day validity date.  Because daily OHLC cannot tell
    which intraday level occurred first, a same-day stop and target is treated
    conservatively as a stop breach.
    """
    if not week_history or not week_dates:
        return []

    friday = max(week_dates)
    seen, trades = set(), []
    ordered = sorted(week_history, key=lambda item: item["date"])

    for snapshot in ordered:
        signal_date = _as_date(snapshot.get("date"))
        if signal_date is None:
            continue
        for stock in snapshot.get("stocks", []):
            symbol = str(stock.get("symbol", ""))
            if not symbol or symbol in seen or stock.get("action") != "BUY_TRIGGER":
                continue
            try:
                trigger = float(stock.get("entry_trigger"))
            except (TypeError, ValueError):
                continue
            if trigger <= 0:
                continue

            valid_until = _as_date(stock.get("entry_valid_until"))
            if valid_until is None:
                valid_until = signal_date + timedelta(days=4)
            end_date = min(valid_until, friday)
            if end_date <= signal_date:
                continue

            rows = conn.execute(
                """SELECT date, high, low, close FROM daily_prices
                   WHERE symbol=? AND date>? AND date<=? ORDER BY date""",
                [symbol, signal_date.isoformat(), end_date.isoformat()],
            ).fetchall()
            fill = next((row for row in rows if float(row[1]) >= trigger), None)
            if fill is None:
                continue

            fill_date = _as_date(fill[0])
            later_rows = conn.execute(
                """SELECT date, high, low, close FROM daily_prices
                   WHERE symbol=? AND date>=? AND date<=? ORDER BY date""",
                [symbol, fill_date.isoformat(), friday.isoformat()],
            ).fetchall()
            sl = float(stock.get("sl", trigger * 0.93))
            t1 = float(stock.get("target1", trigger + (trigger - sl)))
            t2 = float(stock.get("target2", trigger + 2 * (trigger - sl)))
            outcome, exit_price, exit_date = "OPEN", float(later_rows[-1][3]), friday
            t1_hit = t2_hit = False
            for row in later_rows:
                row_date, high, low = _as_date(row[0]), float(row[1]), float(row[2])
                if low <= sl:
                    outcome, exit_price, exit_date = "STOP", sl, row_date
                    break
                if high >= t2:
                    t2_hit = t1_hit = True
                elif high >= t1:
                    t1_hit = True

            return_pct = round((exit_price - trigger) / trigger * 100, 1)
            trades.append(
                {
                    "symbol": symbol,
                    "signal_date": signal_date,
                    "entry_date": fill_date,
                    "entry": trigger,
                    "exit_price": exit_price,
                    "exit_date": exit_date,
                    "return_pct": return_pct,
                    "outcome": outcome,
                    "t1_hit": t1_hit,
                    "t2_hit": t2_hit,
                }
            )
            seen.add(symbol)
    return trades


def analyze_week(week_history, week_prices):
    if not week_history:
        return {"empty": True, "reason": "No scan history for this week"}

    mon = week_history[-1]
    fri = week_history[0]
    mon_stocks = {s["symbol"]: s for s in mon.get("stocks", [])}
    fri_stocks = {s["symbol"]: s for s in fri.get("stocks", [])}
    mon_syms = set(mon_stocks.keys())
    fri_syms = set(fri_stocks.keys())

    performers = []
    sl_hits = []
    t1_hits = []
    t2_hits = []

    for sym, sd in mon_stocks.items():
        if sym not in week_prices:
            continue
        wp = week_prices[sym]
        entry = float(sd.get("close", 0))
        sl = float(sd.get("sl", entry * 0.93))
        t1 = float(sd.get("target1", entry + (entry - sl)))
        t2 = float(sd.get("target2", entry + 2 * (entry - sl)))

        performers.append(
            {
                "symbol": sym,
                "entry": entry,
                "friday_close": wp["friday_close"],
                "week_return_pct": wp["week_return_pct"],
                "week_high": wp["week_high"],
                "week_low": wp["week_low"],
                "sl": sl,
                "target1": t1,
                "target2": t2,
                "score": float(sd.get("score", 0)),
            }
        )

        if wp["week_low"] <= sl:
            sl_hits.append({"symbol": sym, "sl": sl, "week_low": wp["week_low"], "entry": entry})
        if wp["week_high"] >= t1:
            t1_hits.append({"symbol": sym, "target1": t1, "week_high": wp["week_high"], "entry": entry})
        if wp["week_high"] >= t2:
            t2_hits.append({"symbol": sym, "target2": t2, "week_high": wp["week_high"], "entry": entry})

    performers.sort(key=lambda x: x["week_return_pct"], reverse=True)
    total = len(performers)
    winners = sum(1 for p in performers if p["week_return_pct"] > 0)
    losers = sum(1 for p in performers if p["week_return_pct"] < 0)
    flat = total - winners - losers
    hit_rate = round(winners / total * 100, 1) if total else 0
    avg_w = round(sum(p["week_return_pct"] for p in performers if p["week_return_pct"] > 0) / max(winners, 1), 1)
    avg_l = round(sum(p["week_return_pct"] for p in performers if p["week_return_pct"] < 0) / max(losers, 1), 1)

    consistency = []
    all_syms = set()
    for d in week_history:
        all_syms.update(d.get("symbols", []))
    dc = len(week_history)
    for sym in all_syms:
        din = sum(1 for d in week_history if sym in d.get("symbols", []))
        if din == dc and dc >= 3:
            sd = fri_stocks.get(sym, mon_stocks.get(sym, {}))
            wp = week_prices.get(sym, {})
            consistency.append(
                {
                    "symbol": sym,
                    "days": din,
                    "week_return_pct": wp.get("week_return_pct", 0),
                    "score": float(sd.get("score", 0)),
                }
            )
    consistency.sort(key=lambda x: x["week_return_pct"], reverse=True)

    return {
        "empty": False,
        "trading_days": dc,
        "total_tracked": total,
        "top_performers": performers[:5],
        "worst_performers": [p for p in performers[-3:] if p["week_return_pct"] < 0],
        "hit_rate": hit_rate,
        "winners": winners,
        "losers": losers,
        "flat": flat,
        "avg_winner": avg_w,
        "avg_loser": avg_l,
        "sl_hits": sl_hits,
        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "consistency": consistency,
        "new_this_week": list(fri_syms - mon_syms),
        "exited_this_week": list(mon_syms - fri_syms),
        "stayed": len(mon_syms & fri_syms),
        "churn_pct": round(len(fri_syms - mon_syms) / max(len(mon_syms), 1) * 100, 1),
    }


def format_weekly_digest(analysis, week_dates):
    if analysis.get("empty"):
        return (
            f"\U0001f4c5 {_b('Weekly Digest')}\n\n"
            f"{_i(analysis.get('reason', 'No data'))}\n\n"
            "History builds automatically \u2014 check back next Saturday."
        )

    ss = min(week_dates).strftime("%d-%b")
    es = max(week_dates).strftime("%d-%b-%Y")

    msg = f"\U0001f4c5 {_b('Weekly digest ' + chr(8212) + ' ' + ss + ' to ' + es)}\n"
    msg += f"{_i('How did last week' + chr(39) + 's picks perform?')}\n"
    msg += SEP_BOLD + "\n\n"

    # Scorecard
    a = analysis
    msg += f"\U0001f3af {_b('Scorecard')}\n"
    msg += f"Tracked: {a['total_tracked']} stocks \u00b7 Trading days: {a['trading_days']}\n"
    msg += f"\u2705 Winners: {a['winners']} ({_fmt_return(a['avg_winner'])} avg)\n"
    msg += f"\u274c Losers: {a['losers']} ({_fmt_return(a['avg_loser'])} avg)\n"
    msg += f"Hit rate: {_b(str(a['hit_rate']) + '%')}\n"
    msg += SEP_THIN + "\n\n"

    # Top performers
    top = a.get("top_performers", [])
    if top:
        msg += f"\U0001f3c6 {_b('Top performers')}\n"
        for p in top:
            msg += f"\U0001f7e2 {_code(p['symbol'])} {_fmt_price(p['entry'])} \u2192 {_fmt_price(p['friday_close'])} ({_fmt_return(p['week_return_pct'])})\n"
        msg += SEP_THIN + "\n\n"

    # Worst
    worst = a.get("worst_performers", [])
    if worst:
        msg += f"\U0001f4c9 {_b('Underperformers')}\n"
        for p in worst:
            msg += f"\U0001f534 {_code(p['symbol'])} {_fmt_price(p['entry'])} \u2192 {_fmt_price(p['friday_close'])} ({_fmt_return(p['week_return_pct'])})\n"
        msg += SEP_THIN + "\n\n"

    # Target hits
    t1h = a.get("t1_hits", [])
    t2h = a.get("t2_hits", [])
    if t1h or t2h:
        msg += f"\U0001f3af {_b('Target hits')}\n"
        t2s = {t["symbol"] for t in t2h}
        for t in t2h:
            msg += f"\U0001f3af\U0001f3af {_code(t['symbol'])} hit T2 {_fmt_price(t['target2'])} (high: {_fmt_price(t['week_high'])})\n"
        for t in t1h:
            if t["symbol"] not in t2s:
                msg += f"\U0001f3af {_code(t['symbol'])} hit T1 {_fmt_price(t['target1'])} (high: {_fmt_price(t['week_high'])})\n"
        msg += SEP_THIN + "\n\n"

    # SL hits
    slh = a.get("sl_hits", [])
    if slh:
        msg += f"\U0001f6d1 {_b('SL breached')}\n"
        for s in slh:
            msg += (
                f"\u26a0\ufe0f {_code(s['symbol'])} SL {_fmt_price(s['sl'])} hit (low: {_fmt_price(s['week_low'])})\n"
            )
        msg += SEP_THIN + "\n\n"

    # Champions
    champs = a.get("consistency", [])
    if champs:
        msg += f"\U0001f525 {_b('All week champions')}\n"
        for c in champs[:7]:
            e = "\U0001f7e2" if c["week_return_pct"] > 0 else "\U0001f534"
            msg += f"{e} {_code(c['symbol'])} {c['days']}/{a['trading_days']} \u00b7 {c['score']:.0f}/10 \u00b7 Week: {_fmt_return(c['week_return_pct'])}\n"
        msg += SEP_THIN + "\n\n"

    # Churn
    msg += f"\U0001f504 {_b('List churn')}\n"
    msg += f"Stayed all week: {a['stayed']}\n"
    msg += f"New entries: {len(a['new_this_week'])}\n"
    msg += f"Exited: {len(a['exited_this_week'])}\n"
    msg += f"Churn rate: {a['churn_pct']}%\n"
    if a["new_this_week"]:
        msg += f"\n\U0001f195 New: {', '.join(a['new_this_week'][:8])}\n"
    if a["exited_this_week"]:
        msg += f"\U0001f44b Exited: {', '.join(a['exited_this_week'][:8])}\n"

    msg += "\n" + SEP_THIN + "\n"
    msg += f"{_i('Next digest: Next Saturday')}"
    return msg


def format_triggered_weekly_digest(analysis, week_dates):
    """Plain-language weekly report separating paper entries from watchlists."""
    if analysis.get("empty"):
        return f"📅 {_b('NSE SCANNER V3 — WEEKLY REVIEW')}\n{_b('PAPER REVIEW')}\n\n{analysis.get('reason', 'No data')}"

    start = min(week_dates).strftime("%d-%b")
    end = max(week_dates).strftime("%d-%b-%Y")
    trades = analysis.get("model_trades", [])
    winners = [trade for trade in trades if trade["return_pct"] > 0]
    non_winners = [trade for trade in trades if trade["return_pct"] <= 0]
    hit_rate = round(100 * len(winners) / len(trades), 1) if trades else 0
    avg_w = sum(t["return_pct"] for t in winners) / len(winners) if winners else 0
    avg_l = sum(t["return_pct"] for t in non_winners) / len(non_winners) if non_winners else 0

    msg = f"📅 {_b('NSE SCANNER V3 — WEEKLY REVIEW')}\n"
    msg += f"{_b(start + ' to ' + end + ' • PAPER')}\n"
    msg += _i("A paper entry counts only when price crossed its stated entry trigger on a later session.") + "\n"
    msg += SEP_BOLD + "\n\n"
    msg += f"{_b('New paper entries and progress')}\n"
    msg += f"Entries triggered: {len(trades)} | Positive so far: {_b(str(hit_rate) + '%')}\n"
    msg += f"Positive: {len(winners)} ({_fmt_return(avg_w)} avg)\n"
    msg += f"Flat / negative: {len(non_winners)} ({_fmt_return(avg_l)} avg)\n"
    if not trades:
        msg += _i("No watch-for-entry stock crossed its stated entry price this week.") + "\n"
    msg += SEP_THIN + "\n\n"

    if trades:
        msg += f"{_b('Paper position progress')}\n"
        for trade in sorted(trades, key=lambda item: item["return_pct"], reverse=True)[:6]:
            state = "Protective stop reached" if trade["outcome"] == "STOP" else "Paper position open"
            targets = (
                " • Second target reached" if trade["t2_hit"] else " • First target reached" if trade["t1_hit"] else ""
            )
            msg += (
                f"• {_link(trade['symbol'])} — {state}\n"
                f"  {_fmt_price(trade['entry'])} → {_fmt_price(trade['exit_price'])} "
                f"({_fmt_return(trade['return_pct'])}){targets}\n"
            )
        msg += SEP_THIN + "\n\n"

    top = analysis.get("top_performers", [])
    if top:
        msg += f"{_b('Watchlist movement — not entries')}\n"
        for item in top[:5]:
            msg += f"• {_link(item['symbol'])} moved {_fmt_return(item['week_return_pct'])}\n"
        msg += SEP_THIN + "\n\n"

    msg += f"{_b('Watchlist changes')}\n"
    msg += (
        f"Stayed all week: {analysis['stayed']} | New: {len(analysis['new_this_week'])} | "
        f"Exited: {len(analysis['exited_this_week'])}\n"
    )
    msg += f"Churn rate: {analysis['churn_pct']}%\n"
    if analysis["new_this_week"]:
        msg += f"New: {', '.join(analysis['new_this_week'][:8])}\n"
    msg += "\n" + SEP_THIN + "\n" + _i("Next: Review watch-for-entry stocks only after their stated trigger.")
    msg += "\nResearch and paper tracking only — not investment advice."
    return msg


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def format_v3_weekly_review(daily, state, week_dates):
    """Build the weekly topic from the current V3 output and durable paper state."""
    start = min(week_dates).strftime("%d-%b")
    end = max(week_dates).strftime("%d-%b-%Y")
    tables = state.get("tables", {}) if isinstance(state, dict) else {}
    positions = tables.get("v2_positions", [])
    active = [row for row in positions if row.get("state") in {"OPEN", "PARTIAL", "TRAILING"}]
    week_set = {day.isoformat() for day in week_dates}
    events = [row for row in tables.get("v2_position_events", []) if str(row.get("event_date", ""))[:10] in week_set]
    new_entries = [row for row in events if row.get("event_type") in {"CREATE", "ENTRY", "OPEN"}]
    exits = [row for row in events if row.get("to_state") == "CLOSED" or row.get("event_type") == "EXIT"]
    snapshots = sorted(
        (row for row in tables.get("v2_portfolio_snapshots", []) if str(row.get("portfolio_date")) in week_set),
        key=lambda row: row.get("portfolio_date", ""),
    )
    pnl_change = 0.0
    if snapshots:
        pnl_change = float(snapshots[-1].get("total_pnl", 0) or 0) - float(snapshots[0].get("total_pnl", 0) or 0)

    regime = str(daily.get("regime", "UNKNOWN")).upper()
    regime_text = {
        "BULL": "Supportive",
        "BULLISH": "Supportive",
        "NEUTRAL": "Mixed",
        "BEAR": "Weak — new entries restricted",
        "BEARISH": "Weak — new entries restricted",
    }.get(regime, "Not available")
    candidates = list(daily.get("dashboard_candidates", []))
    ready = [row for row in candidates if row.get("timing_state") == "READY" or row.get("classification") == "ACTION"]
    waiting = [row for row in candidates if row not in ready]

    lines = [
        "📅 <b>NSE SCANNER V3 — WEEKLY REVIEW</b>",
        f"<b>{start} to {end} • PAPER</b>",
        f"Latest market data: {daily.get('trade_date') or 'Not available'} EOD",
        f"Market condition: <b>{regime_text}</b>",
        "",
        "📂 <b>Paper portfolio</b>",
        f"New paper entries: {len(new_entries)} • Exits: {len(exits)} • Still open: {len(active)}",
        f"Change in recorded P&amp;L this week: {_fmt_price(pnl_change)}",
        "",
    ]
    if active:
        for row in active[:5]:
            entry = float(row.get("entry", 0) or 0)
            latest = float(row.get("last_price", entry) or entry)
            move = ((latest / entry) - 1) * 100 if entry else 0.0
            lines.extend(
                [
                    "━━━━━━━━━━━━━━",
                    f"📂 {_link(row.get('symbol', ''))} — PAPER POSITION OPEN",
                    f"Entry {_fmt_price(entry)} → Latest {_fmt_price(latest)} ({_fmt_return(move)})",
                    f"Protect below {_fmt_price(row.get('stop', 0))}",
                    "Next: Continue only while price stays above the protection level.",
                ]
            )
    else:
        lines.append("No open V3 paper positions. No portfolio action required.")

    lines.extend(
        [
            "",
            "👀 <b>Current opportunity list</b>",
            f"Watch for entry: {len(ready)} • Waiting for confirmation: {len(waiting)}",
        ]
    )
    for row in (ready + waiting)[:5]:
        label = "Watch for entry" if row in ready else "Watchlist—wait for confirmation"
        lines.append(
            f"• {_link(row.get('symbol', ''))} — {label} • Opportunity score {float(row.get('score', 0) or 0):.0f}/100"
        )
    if not candidates:
        lines.append("No current V3 opportunity passed the display threshold.")
    lines.extend(
        [
            "",
            "Next: Act only after a stated entry trigger; do not treat a watchlist item as an entry.",
            "Research and paper tracking only — not investment advice.",
        ]
    )
    return "\n".join(lines)


def generate_weekly_digest(week_ending=None, dry_run=False):
    if week_ending is None:
        today = date.today()
        days_since = (today.weekday() - 4) % 7
        if days_since == 0 and today.weekday() != 4:
            days_since = 7
        week_ending = today - timedelta(days=days_since)

    week_dates = get_week_dates(week_ending)
    if not week_dates:
        return False

    daily = _read_json("output/v2_daily_run.json", {})
    state = _read_json("v2_portfolio_state.json", {})
    message = format_v3_weekly_review(daily, state, week_dates)

    if dry_run:
        import re

        print(re.sub(r"<[^>]+>", "", message))
    else:
        token = os.getenv("V3_TELEGRAM_BOT_TOKEN", "").strip()
        cid = os.getenv("V3_TELEGRAM_CHAT_ID", "").strip()
        if token and cid:
            try:
                payload = {
                    "chat_id": cid,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": dashboard_keyboard("v3"),
                }
                topic_id = os.getenv("V3_WEEKLY_TOPIC_ID")
                if topic_id and topic_id.isdigit():
                    payload["message_thread_id"] = int(topic_id)
                else:
                    log.error("V3_WEEKLY_TOPIC_ID is missing or invalid")
                    return False
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=20)
                r.raise_for_status()
                return bool(r.json().get("ok"))
            except (requests.RequestException, ValueError) as exc:
                log.exception("Telegram weekly delivery failed: %s", type(exc).__name__)
                return False
        log.error("V3 Telegram credentials are missing")
        return False
    return True


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--week-ending", type=str)
    a = p.parse_args()
    we = None
    if a.week_ending:
        for f in ["%d-%m-%Y", "%Y-%m-%d"]:
            try:
                we = datetime.strptime(a.week_ending, f).date()
                break
            except:
                pass
    raise SystemExit(0 if generate_weekly_digest(week_ending=we, dry_run=a.dry_run) else 1)
