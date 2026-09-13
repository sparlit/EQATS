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
nse_signal_tracker.py — Frozen Entry + Probability + Lifecycle Engine (v2)
===========================================================================
WHAT CHANGED FROM v1:
  1. calculate_probability() now accepts situation, cross_age, dist_pct
     — Situation PRIME adds probability bonus
     — Situation AVOID/BOOK reduces probability
     — Fresh cross (≤10d) adds bonus
     — Room to run (dist ≤ 5%) adds bonus

  2. update_tracker() now saves situation to signal record

  3. set_category() kept for backwards compatibility

Everything else (lifecycle states, milestones, P/L,
format functions) unchanged.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

_HERE = Path(__file__).parent
TRACKER_FILE = _HERE / "signal_tracker.json"

STATE_ACTIVE = "active"
STATE_T1_HIT = "t1_hit"
STATE_T2_HIT = "t2_hit"
STATE_WEAKENING = "weakening"
STATE_EXITED = "exited"

# ── Probability constants — try to load from config ───────────
try:
    import config as _cfg

    PROB_BASE = getattr(_cfg, "PROB_BASE", 40)
    PROB_SCORE_PRIME = getattr(_cfg, "PROB_SCORE_PRIME", 25)
    PROB_SCORE_HIGH = getattr(_cfg, "PROB_SCORE_HIGH", 20)
    PROB_SCORE_MED = getattr(_cfg, "PROB_SCORE_MED", 10)
    PROB_FRESH_CROSS = getattr(_cfg, "PROB_FRESH_CROSS", 15)
    PROB_YOUNG_CROSS = getattr(_cfg, "PROB_YOUNG_CROSS", 8)
    PROB_ROOM_TIGHT = getattr(_cfg, "PROB_ROOM_TIGHT", 10)
    PROB_ROOM_OK = getattr(_cfg, "PROB_ROOM_OK", 5)
    PROB_STREAK_5 = getattr(_cfg, "PROB_STREAK_5", 10)
    PROB_STREAK_10 = getattr(_cfg, "PROB_STREAK_10", 15)
    PROB_CAT_UPTREND = getattr(_cfg, "PROB_CAT_UPTREND", 8)
    PROB_CAT_RISING = getattr(_cfg, "PROB_CAT_RISING", 6)
    PROB_CAT_SAFE = getattr(_cfg, "PROB_CAT_SAFE", 4)
    PROB_T2_DISCOUNT = getattr(_cfg, "PROB_T2_DISCOUNT", 16)
    PROB_PENALTY_OVEREXT = getattr(_cfg, "PROB_PENALTY_OVEREXT", -15)
    PROB_PENALTY_BOOK = getattr(_cfg, "PROB_PENALTY_BOOK", -10)
    PROB_PENALTY_AVOID = getattr(_cfg, "PROB_PENALTY_AVOID", -20)
    SITUATION_PRIME = getattr(_cfg, "SITUATION_PRIME", "prime")
    SITUATION_AVOID = getattr(_cfg, "SITUATION_AVOID", "avoid")
    SITUATION_BOOK = getattr(_cfg, "SITUATION_BOOK", "book")
    SITUATION_HOLD = getattr(_cfg, "SITUATION_HOLD", "hold")
except ImportError:
    PROB_BASE = 40
    PROB_SCORE_PRIME = 25
    PROB_SCORE_HIGH = 20
    PROB_SCORE_MED = 10
    PROB_FRESH_CROSS = 15
    PROB_YOUNG_CROSS = 8
    PROB_ROOM_TIGHT = 10
    PROB_ROOM_OK = 5
    PROB_STREAK_5 = 10
    PROB_STREAK_10 = 15
    PROB_CAT_UPTREND = 8
    PROB_CAT_RISING = 6
    PROB_CAT_SAFE = 4
    PROB_T2_DISCOUNT = 16
    PROB_PENALTY_OVEREXT = -15
    PROB_PENALTY_BOOK = -10
    PROB_PENALTY_AVOID = -20
    SITUATION_PRIME = "prime"
    SITUATION_AVOID = "avoid"
    SITUATION_BOOK = "book"
    SITUATION_HOLD = "hold"


def _load_tracker():
    if not TRACKER_FILE.exists():
        return {"signals": {}, "exited": [], "last_updated": ""}
    try:
        with open(TRACKER_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"signals": {}, "exited": [], "last_updated": ""}


def _save_tracker(data):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# PROBABILITY CALCULATION — Updated with situation awareness
# ═══════════════════════════════════════════════════════════════


def calculate_probability(
    score=0,
    streak=0,
    category="",
    current_price=0,
    entry_price=0,
    sl_price=0,
    t1_price=0,
    situation="",
    cross_age=999,
    dist_pct=0,
):
    """
    Calculate T1/T2 probability using forward signals.

    New inputs (v2):
      situation  : prime/watch/hold/book/avoid
      cross_age  : days since HMA20 crossed above HMA55
      dist_pct   : % distance of close above HMA55

    Returns:
      {"t1_pct": int, "t2_pct": int, "sl_pct": int}
    """
    score = float(score or 0)
    cross_age = int(cross_age or 999)
    dist_pct = float(dist_pct or 0)

    t1 = PROB_BASE

    # ── Score bonus ───────────────────────────────────────────
    if score >= 8:
        t1 += PROB_SCORE_PRIME
    elif score >= 7 or score >= 6:
        t1 += PROB_SCORE_HIGH
    elif score >= 4:
        t1 += PROB_SCORE_MED

    # ── HMA freshness bonus (NEW) ─────────────────────────────
    if cross_age <= 10:
        t1 += PROB_FRESH_CROSS
    elif cross_age <= 20:
        t1 += PROB_YOUNG_CROSS

    # ── Room to run bonus (NEW) ───────────────────────────────
    if dist_pct <= 5.0:
        t1 += PROB_ROOM_TIGHT
    elif dist_pct <= 10.0:
        t1 += PROB_ROOM_OK

    # ── Streak bonus ──────────────────────────────────────────
    if streak >= 10:
        t1 += PROB_STREAK_10
    elif streak >= 5:
        t1 += PROB_STREAK_5

    # ── Category bonus ────────────────────────────────────────
    cat = category.lower() if category else ""
    if "uptrend" in cat or "prime" in cat:
        t1 += PROB_CAT_UPTREND
    elif "rising" in cat or "consistent" in cat:
        t1 += PROB_CAT_RISING
    elif "safer" in cat or "safe" in cat:
        t1 += PROB_CAT_SAFE

    # ── Progress toward T1 bonus ─────────────────────────────
    if current_price > 0 and entry_price > 0 and t1_price > 0:
        distance_to_t1 = t1_price - current_price
        total_distance = t1_price - entry_price
        if total_distance > 0:
            progress = 1 - (distance_to_t1 / total_distance)
            if progress > 0.5:
                t1 += int(progress * 10)

    # ── Situation adjustments (NEW) ───────────────────────────
    if situation == SITUATION_PRIME:
        t1 += 8  # Prime = confirmed high probability
    elif situation == SITUATION_HOLD:
        t1 += 5  # Hold = sustained momentum
    elif situation == SITUATION_BOOK:
        t1 += PROB_PENALTY_BOOK  # Book = declining forward probability
    elif situation == SITUATION_AVOID:
        t1 += PROB_PENALTY_AVOID  # Avoid = low probability

    # ── Overextension penalty ─────────────────────────────────
    if dist_pct > 15.0:
        t1 += PROB_PENALTY_OVEREXT

    # ── Clamp and derive T2, SL ───────────────────────────────
    t1 = max(15, min(85, t1))
    t2 = max(10, t1 - PROB_T2_DISCOUNT)
    sl = max(10, min(50, 100 - t1))

    return {"t1_pct": t1, "t2_pct": t2, "sl_pct": sl}


# ═══════════════════════════════════════════════════════════════
# STATE DETERMINATION (unchanged)
# ═══════════════════════════════════════════════════════════════


def _determine_state(signal, current_stock=None):
    if current_stock is None:
        return STATE_EXITED

    score = float(current_stock.get("score", 0))
    t1 = float(signal.get("t1_price", 0))
    t2 = float(signal.get("t2_price", 0))
    high = float(signal.get("highest_price", 0))

    if t2 > 0 and high >= t2:
        return STATE_T2_HIT
    if t1 > 0 and high >= t1:
        return STATE_T1_HIT
    if score <= 5:
        return STATE_WEAKENING

    prev_score = float(signal.get("prev_score", score))
    if prev_score > 0 and score < prev_score - 1.5:
        return STATE_WEAKENING

    return STATE_ACTIVE


# ═══════════════════════════════════════════════════════════════
# UPDATE TRACKER — Saves situation to signal record
# ═══════════════════════════════════════════════════════════════


def update_tracker(current_stocks, scan_date, history=None):
    """
    Update tracker with latest scan. Now stores situation field.
    """
    tracker = _load_tracker()
    signals = tracker.get("signals", {})
    exited = tracker.get("exited", [])

    current_symbols = {s["symbol"] for s in current_stocks}
    current_map = {s["symbol"]: s for s in current_stocks}

    # Build streak map
    streaks = {}
    if history:
        for symbol in current_symbols:
            count = 0
            for day_entry in history:
                if symbol in day_entry.get("symbols", []):
                    count += 1
                else:
                    break
            streaks[symbol] = count

    new_count = updated_count = exited_count = 0

    for symbol, stock in current_map.items():
        close = float(stock.get("close", 0))
        score = float(stock.get("score", 0))
        sl = float(stock.get("sl", round(close * 0.93, 2)))
        t1 = float(stock.get("target1", round(close + (close - sl), 2)))
        t2 = float(stock.get("target2", round(close + 2 * (close - sl), 2)))
        streak = streaks.get(symbol, 1)
        situation = stock.get("situation", "watch")
        cross_age = int(stock.get("cross_age", 999))
        dist_pct = float(stock.get("dist_pct", 0))

        # Calculate probability with new signals
        prob = calculate_probability(
            score=score,
            streak=streak,
            situation=situation,
            cross_age=cross_age,
            dist_pct=dist_pct,
        )

        if symbol not in signals:
            signals[symbol] = {
                "symbol": symbol,
                "entry_price": close,
                "entry_date": scan_date,
                "sl_price": sl,
                "t1_price": t1,
                "t2_price": t2,
                "current_price": close,
                "highest_price": close,
                "lowest_price": close,
                "entry_score": score,
                "current_score": score,
                "prev_score": score,
                "streak": streak,
                "state": STATE_ACTIVE,
                "situation": situation,
                "cross_age": cross_age,
                "dist_pct": dist_pct,
                "t1_prob": prob["t1_pct"],
                "t2_prob": prob["t2_pct"],
                "sl_prob": prob["sl_pct"],
                "milestones": [{"event": "entered", "date": scan_date, "price": close}],
                "t1_hit_date": None,
                "t2_hit_date": None,
                "category": stock.get("category", ""),
            }
            new_count += 1
        else:
            sig = signals[symbol]
            sig["prev_score"] = sig.get("current_score", score)
            sig["current_price"] = close
            sig["current_score"] = score
            sig["streak"] = streak
            sig["situation"] = situation
            sig["cross_age"] = cross_age
            sig["dist_pct"] = dist_pct
            sig["t1_prob"] = prob["t1_pct"]
            sig["t2_prob"] = prob["t2_pct"]
            sig["sl_prob"] = prob["sl_pct"]

            if close > sig.get("highest_price", 0):
                sig["highest_price"] = close
            if close < sig.get("lowest_price", close):
                sig["lowest_price"] = close

            if sig.get("t1_hit_date") is None and sig["highest_price"] >= sig["t1_price"] > 0:
                sig["t1_hit_date"] = scan_date
                sig["milestones"].append({"event": "t1_hit", "date": scan_date, "price": sig["highest_price"]})

            if sig.get("t2_hit_date") is None and sig["highest_price"] >= sig["t2_price"] > 0:
                sig["t2_hit_date"] = scan_date
                sig["milestones"].append({"event": "t2_hit", "date": scan_date, "price": sig["highest_price"]})

            sig["state"] = _determine_state(sig, stock)
            updated_count += 1

    # Handle exits
    for symbol in list(signals.keys()):
        if symbol not in current_symbols:
            sig = signals[symbol]
            sig["state"] = STATE_EXITED
            sig["exit_date"] = scan_date
            sig["exit_price"] = sig["current_price"]

            entry = sig["entry_price"]
            exit_p = sig["current_price"]
            if entry > 0:
                sig["final_pl"] = round(exit_p - entry, 2)
                sig["final_pl_pct"] = round((exit_p - entry) / entry * 100, 1)
                days = 0
                if sig.get("entry_date"):
                    try:
                        ed = datetime.strptime(str(sig["entry_date"])[:10], "%Y-%m-%d").date()
                        td = datetime.strptime(str(scan_date)[:10], "%Y-%m-%d").date()
                        days = (td - ed).days
                    except Exception:
                        pass
                sig["days_in_list"] = days
            else:
                sig["final_pl"] = 0
                sig["final_pl_pct"] = 0
                sig["days_in_list"] = 0

            sig["milestones"].append({"event": "exited", "date": scan_date, "price": exit_p})

            exited.append(dict(sig))
            del signals[symbol]
            exited_count += 1

    # Keep only last 100 exited
    if len(exited) > 100:
        exited = exited[-100:]

    tracker["signals"] = signals
    tracker["exited"] = exited
    tracker["last_updated"] = str(scan_date)
    _save_tracker(tracker)

    return f"Tracker: +{new_count} new, ~{updated_count} updated, -{exited_count} exited"


# ═══════════════════════════════════════════════════════════════
# QUERY FUNCTIONS
# ═══════════════════════════════════════════════════════════════


def get_signal(symbol):
    tracker = _load_tracker()
    if symbol in tracker.get("signals", {}):
        return tracker["signals"][symbol]
    for sig in tracker.get("exited", []):
        if sig["symbol"] == symbol:
            return sig
    return None


def get_live_signals():
    return list(_load_tracker().get("signals", {}).values())


def get_exited_signals():
    return _load_tracker().get("exited", [])


def set_category(symbol, category_label):
    """Kept for backwards compatibility with nse_smart_buckets."""
    tracker = _load_tracker()
    if symbol in tracker.get("signals", {}):
        tracker["signals"][symbol]["category"] = category_label
        _save_tracker(tracker)


def get_tracker_summary():
    tracker = _load_tracker()
    signals = tracker.get("signals", {})
    all_sigs = list(signals.values())

    active = [s for s in all_sigs if s["state"] == STATE_ACTIVE]
    t1_hit = [s for s in all_sigs if s["state"] == STATE_T1_HIT]
    t2_hit = [s for s in all_sigs if s["state"] == STATE_T2_HIT]
    weakening = [s for s in all_sigs if s["state"] == STATE_WEAKENING]

    # Situation breakdown
    prime_count = sum(1 for s in all_sigs if s.get("situation") == SITUATION_PRIME)

    avg_t1 = round(sum(s.get("t1_prob", 0) for s in all_sigs) / len(all_sigs)) if all_sigs else 0
    avg_t2 = round(sum(s.get("t2_prob", 0) for s in all_sigs) / len(all_sigs)) if all_sigs else 0
    high_prob = [s for s in all_sigs if s.get("t1_prob", 0) >= 70]

    return {
        "total_active": len(signals),
        "active": len(active),
        "t1_hit": len(t1_hit),
        "t2_hit": len(t2_hit),
        "weakening": len(weakening),
        "prime_count": prime_count,
        "total_exited": len(tracker.get("exited", [])),
        "avg_t1_prob": avg_t1,
        "avg_t2_prob": avg_t2,
        "high_prob_count": len(high_prob),
        "last_updated": tracker.get("last_updated", ""),
    }


# ═══════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════


def _h(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _b(v):
    return f"<b>{_h(v)}</b>"


def _code(v):
    return f"<code>{_h(v)}</code>"


def _fmt_price(p):
    return f"₹{round(float(p)):,}"


def _fmt_pl(entry, current):
    entry = float(entry)
    current = float(current)
    if entry <= 0:
        return "N/A"
    diff = current - entry
    pct = diff / entry * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{round(diff):,} ({sign}{pct:.1f}%)"


def format_signal_card(symbol):
    sig = get_signal(symbol)
    if not sig:
        return f"No signal data found for {_code(symbol)}"

    state = sig.get("state", STATE_ACTIVE)
    situation = sig.get("situation", "")
    cross_age = int(sig.get("cross_age", 999))
    dist_pct = float(sig.get("dist_pct", 0))

    state_badges = {
        STATE_ACTIVE: "Active",
        STATE_T1_HIT: "T1 Hit ✅",
        STATE_T2_HIT: "T2 Hit 🎯",
        STATE_WEAKENING: "Weakening ⚠️",
        STATE_EXITED: "Exited",
    }
    badge = state_badges.get(state, "Unknown")

    entry = float(sig.get("entry_price", 0))
    current = float(sig.get("current_price", 0))
    sl = float(sig.get("sl_price", 0))
    t1 = float(sig.get("t1_price", 0))
    t2 = float(sig.get("t2_price", 0))
    score = round(float(sig.get("current_score", 0)))
    streak = sig.get("streak", 0)
    t1_prob = sig.get("t1_prob", 0)
    t2_prob = sig.get("t2_prob", 0)
    sl_prob = sig.get("sl_prob", 0)

    # Situation display
    try:
        from config import SITUATION_META

        sm = SITUATION_META.get(situation, {})
        sit_str = f"{sm.get('icon', '')} {sm.get('label', situation)}"
    except Exception:
        sit_str = situation.title() if situation else ""

    msg = f"{_code(symbol)}  {score}/10  [{badge}]\n"
    if sit_str:
        msg += f"Situation: {sit_str}\n"
    msg += "━" * 28 + "\n"
    msg += f"Entry (frozen): {_fmt_price(entry)}\n"
    msg += f"Current price:  {_fmt_price(current)}\n"
    msg += f"Live P/L:       {_fmt_pl(entry, current)}\n"
    msg += f"Stop-loss:      {_fmt_price(sl)}\n"
    msg += f"Target 1:       {_fmt_price(t1)}\n"
    msg += f"Target 2:       {_fmt_price(t2)}\n"
    msg += f"\nT1 prob: {t1_prob}% | T2 prob: {t2_prob}%"
    if state == STATE_WEAKENING:
        msg += f" | SL risk: {sl_prob}%"
    msg += "\n"

    # Forward signal context
    if cross_age > 0 and cross_age < 999:
        msg += f"HMA cross: {cross_age} days ago\n"
    if dist_pct > 0:
        msg += f"HMA55 dist: {dist_pct:.1f}%\n"

    if streak > 0:
        msg += f"In list: {streak} consecutive days\n"

    milestones = sig.get("milestones", [])
    if milestones:
        msg += f"\n{_b('Milestones')}\n"
        event_labels = {
            "entered": "Entered top 25",
            "t1_hit": "T1 target hit",
            "t2_hit": "T2 target hit",
            "exited": "Left top 25",
        }
        for m in milestones:
            label = event_labels.get(m["event"], m["event"])
            price = _fmt_price(m.get("price", 0))
            msg += f"  {str(m['date'])[:10]}  {label}  {price}\n"

    if state == STATE_WEAKENING:
        msg += f"\n{_b('Warning')}: Score dropping. Consider tightening SL or booking profits."

    if state == STATE_EXITED:
        days = sig.get("days_in_list", 0)
        final_pl = sig.get("final_pl_pct", 0)
        sign = "+" if final_pl >= 0 else ""
        msg += f"\nFinal return: {sign}{final_pl}% in {days} days"

    return msg


def format_stock_with_prob(stock, signal=None, rank=0, show_frozen=False):
    sym = stock.get("symbol", "?")
    score = round(float(stock.get("score", 0)))
    close = float(stock.get("close", 0))
    r3m = float(stock.get("return_3m_pct", 0))
    sl = float(stock.get("sl", round(close * 0.93, 2)))
    t1 = float(stock.get("target1", round(close + (close - sl), 2)))
    t2 = float(stock.get("target2", round(close + 2 * (close - sl), 2)))

    if signal:
        t1_prob = signal.get("t1_prob", 0)
        t2_prob = signal.get("t2_prob", 0)
        streak = signal.get("streak", 0)
        entry = signal.get("entry_price", close)
    else:
        prob = calculate_probability(score=score)
        t1_prob = prob["t1_pct"]
        t2_prob = prob["t2_pct"]
        streak = 0
        entry = close

    r3m_sign = "+" if r3m >= 0 else ""
    rank_str = f"{_b(str(rank) + '.')} " if rank > 0 else ""
    streak_str = f" | {streak}d" if streak >= 3 else ""

    msg = f"{rank_str}{_code(sym)}  {score}/10{streak_str}\n"
    if show_frozen and signal and signal.get("entry_price"):
        pl_str = _fmt_pl(entry, close)
        msg += f"   Entry(frozen) {_fmt_price(entry)} | Now {_fmt_price(close)} | P/L {pl_str}\n"
    msg += f"   Entry {_fmt_price(close)} | SL {_fmt_price(sl)} | T1 {_fmt_price(t1)} | T2 {_fmt_price(t2)}\n"
    msg += f"   3M {r3m_sign}{r3m:.1f}% | T1 {t1_prob}% | T2 {t2_prob}%\n"
    return msg


def format_exit_card(sig):
    symbol = sig.get("symbol", "?")
    entry = float(sig.get("entry_price", 0))
    exit_p = float(sig.get("exit_price", sig.get("current_price", 0)))
    days = sig.get("days_in_list", 0)
    score = round(float(sig.get("entry_score", 0)))
    final_pl = sig.get("final_pl_pct", 0)
    t1_hit = sig.get("t1_hit_date") is not None
    pl_sign = "+" if final_pl >= 0 else ""

    msg = f"{_code(symbol)}  was {score}/10  [Exited]\n"
    msg += f"   Was in list {days} days\n"
    msg += f"   Entry {_fmt_price(entry)} → Exit {_fmt_price(exit_p)}\n"
    msg += f"   Final P/L: {pl_sign}{final_pl}%"
    if t1_hit:
        msg += " | T1 was hit ✅"
    msg += "\n"
    return msg


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Signal Tracker v2")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stock", type=str, help="Show signal card for SYMBOL")
    args = parser.parse_args()

    if args.status:
        s = get_tracker_summary()
        print(f"Active  : {s['total_active']} | Exited: {s['total_exited']}")
        print(f"T1 hit  : {s['t1_hit']} | T2 hit: {s['t2_hit']}")
        print(f"Prime   : {s['prime_count']} | Weakening: {s['weakening']}")
        print(f"Avg T1  : {s['avg_t1_prob']}% | Avg T2: {s['avg_t2_prob']}%")
        print(f"T1>70%  : {s['high_prob_count']} stocks")
    elif args.stock:
        import re

        print(re.sub(r"<[^>]+>", "", format_signal_card(args.stock.upper())))
    else:
        parser.print_help()
