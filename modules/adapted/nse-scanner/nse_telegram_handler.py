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
nse_telegram_handler.py — Telegram Bot Handler (v6 — Situation Engine)
========================================================================
WHAT CHANGED FROM v5:
  1. SITUATION ENGINE added
     - assign_situation() maps each stock to prime/watch/hold/book/avoid
     - format_today_scan() now groups by situation (not category)
     - format_prime_stocks() — new dedicated PRIME ENTRY view
     - format_situation_scan() — full situation-grouped message

  2. STOCK CARD updated
     - Shows situation label + action advice
     - Shows signal breakdown (cross age, room, volume)
     - 3M return shown as (ref) not as ranking signal

  3. PROBABILITY updated
     - Now uses freshness + room + situation in calculation
     - Situation AVOID/BOOK reduce probability appropriately

  4. SORT updated
     - Default sort = by forward score (not 3M return)
     - 3M sort still available as option

  5. HELP updated
     - New /prime command documented
     - Situation descriptions added

  v6.1: Portfolio commands added
     - format_portfolio() — open positions + live P/L
     - format_exits()     — closed trade history
     - format_returns()   — win rate + performance stats

All other functions (save/load, history, news,
new/exit/strong/caution formats) unchanged.
"""

import argparse
import json
import math
import os
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(_HERE, "telegram_last_scan.json")
HISTORY_FILE = os.path.join(_HERE, "scan_history.json")
PARSE_MODE = "HTML"
HISTORY_DAYS = 30

try:
    import config

    SITUATION_META = getattr(config, "SITUATION_META", {})
    SITUATION_ORDER = getattr(config, "SITUATION_ORDER", ["prime", "hold", "watch", "book", "avoid"])
    SITUATION_PRIME = getattr(config, "SITUATION_PRIME", "prime")
    SITUATION_WATCH = getattr(config, "SITUATION_WATCH", "watch")
    SITUATION_HOLD = getattr(config, "SITUATION_HOLD", "hold")
    SITUATION_BOOK = getattr(config, "SITUATION_BOOK", "book")
    SITUATION_AVOID = getattr(config, "SITUATION_AVOID", "avoid")
except ImportError:
    config = None
    SITUATION_META = {
        "prime": {"icon": "🎯", "label": "Prime Entry", "action": "Enter today — confirm on TradingView"},
        "watch": {"icon": "👀", "label": "Watch Closely", "action": "Good setup. One condition missing."},
        "hold": {"icon": "💰", "label": "Hold & Trail", "action": "Already in move — trail your stop loss."},
        "book": {"icon": "⚠️", "label": "Book Profits", "action": "Move maturing — protect gains."},
        "avoid": {"icon": "🚫", "label": "Avoid Now", "action": "Weak setup — skip today."},
    }
    SITUATION_ORDER = ["prime", "hold", "watch", "book", "avoid"]
    SITUATION_PRIME = "prime"
    SITUATION_WATCH = "watch"
    SITUATION_HOLD = "hold"
    SITUATION_BOOK = "book"
    SITUATION_AVOID = "avoid"

_TRACKER_OK = False
try:
    from nse_signal_tracker import (
        STATE_ACTIVE,
        STATE_EXITED,
        STATE_T1_HIT,
        STATE_T2_HIT,
        STATE_WEAKENING,
        calculate_probability,
        get_signal,
        get_tracker_summary,
    )

    _TRACKER_OK = True
except ImportError:

    def get_signal(s):
        return None

    def calculate_probability(**kw):
        return {"t1_pct": 0, "t2_pct": 0, "sl_pct": 0}

    def get_tracker_summary():
        return {}


# ── Category metadata (kept for backwards compatibility) ──────
CATEGORY_META = {
    "rising": {"icon": "📈", "label": "Consistently Rising", "desc": "Steady momentum, early in the move"},
    "uptrend": {"icon": "🚀", "label": "Clear Uptrend Confirmed", "desc": "Fresh cross, room to run, volume confirmed"},
    "peak": {"icon": "🔝", "label": "Close to Their Peak", "desc": "Near 52-week highs — strong institutional demand"},
    "recovering": {"icon": "📉", "label": "Recovering from a Fall", "desc": "Bouncing back — early recovery signal"},
    "safer": {
        "icon": "🛡️",
        "label": "Safer Bets with Good Reward",
        "desc": "Tight stop, high delivery, lower risk setup",
    },
}
CATEGORY_ORDER = ["uptrend", "rising", "peak", "safer", "recovering"]

SEP_BOLD = "━" * 17
SEP_THIN = "─" * 18


# ═══════════════════════════════════════════════════════════════
# HTML HELPERS
# ═══════════════════════════════════════════════════════════════


def _h(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _b(v):
    return f"<b>{_h(v)}</b>"


def _i(v):
    return f"<i>{_h(v)}</i>"


def _code(v):
    return f"<code>{_h(v)}</code>"


def _fmt_price(p):
    return f"₹{round(float(p)):,}"


def _fmt_return(pct):
    pct = float(pct)
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _fmt_pl(entry, current):
    entry = float(entry)
    current = float(current)
    if entry <= 0:
        return "N/A"
    diff = current - entry
    pct = diff / entry * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{round(diff):,} ({sign}{pct:.1f}%)"


def _date_str(scan_date):
    try:
        return datetime.strptime(scan_date or "", "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        return scan_date or "Today"


def _to_int(value, default=0):
    """Safe int conversion that handles None/NaN/string values."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("", "nan", "none", "null"):
                return default
        return int(float(value))
    except Exception:
        return default


def _to_float(value, default=0.0):
    """Safe float conversion that handles None/NaN/string values."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("", "nan", "none", "null"):
                return default
        out = float(value)
        if out != out:  # NaN check
            return default
        return out
    except Exception:
        return default


def _to_bool(value, default=False):
    """Safe bool conversion for mixed JSON/CSV/pandas values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y"):
            return True
        if v in ("false", "0", "no", "n", "", "nan", "none", "null"):
            return False
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return False
        return value != 0
    return bool(value)


# ═══════════════════════════════════════════════════════════════
# SITUATION ENGINE
# ═══════════════════════════════════════════════════════════════


def assign_situation(stock: dict, streak: int = 0) -> str:
    """
    Assign a situation label to a stock based on forward signals.

    Priority order:
      1. AVOID   — score ≤ 3 OR distribution volume OR bearish
      2. BOOK    — cross age > 30d OR >15% stretched
      3. HOLD    — streak ≥ 5 days AND score still OK
      4. PRIME   — score ≥ 7 + fresh cross + not overextended
      5. WATCH   — everything else that passes

    Args:
        stock:  stock dict from scan results
        streak: consecutive days in scanner list

    Returns:
        situation string: prime/watch/hold/book/avoid
    """
    score = _to_float(stock.get("score", 0), 0.0)
    cross_age = _to_int(stock.get("cross_age", 999), 999)
    dist_pct = _to_float(stock.get("dist_pct", 0), 0.0)
    overextended = _to_bool(stock.get("overextended", False), False)
    _to_bool(stock.get("fresh_cross", False), False)
    acc_days = _to_int(stock.get("acc_days", 0), 0)
    dist_days = _to_int(stock.get("dist_days", 0), 0)

    score = float(stock.get("score", 0))
    cross_age = int(stock.get("cross_age", 999))
    dist_pct = float(stock.get("dist_pct", 0))
    overextended = bool(stock.get("overextended", False))
    bool(stock.get("fresh_cross", False))
    acc_days = int(stock.get("acc_days", 0))
    dist_days = int(stock.get("dist_days", 0))
    obv_dir = str(stock.get("obv_dir", "flat"))
    r3m = _to_float(stock.get("return_3m_pct", 0), 0.0)

    if score <= 3:
        return SITUATION_AVOID
    if dist_days >= 4 and obv_dir == "falling":
        return SITUATION_AVOID
    if cross_age == -1:
        return SITUATION_AVOID

    if overextended and cross_age > 20:
        return SITUATION_BOOK
    if cross_age > 30 and dist_pct > 10:
        return SITUATION_BOOK
    if r3m > 40 and score < 6:
        return SITUATION_BOOK

    if streak >= 5 and score >= 5:
        return SITUATION_HOLD

    if score >= 7 and not overextended and cross_age <= 20 and acc_days >= 3:
        return SITUATION_PRIME

    return SITUATION_WATCH


def get_situation_signal_line(stock: dict) -> str:
    parts = []

    cross_age = _to_int(stock.get("cross_age", 999), 999)
    dist_pct = _to_float(stock.get("dist_pct", 0), 0.0)
    fresh_cross = _to_bool(stock.get("fresh_cross", False), False)
    overextended = _to_bool(stock.get("overextended", False), False)
    acc_days = _to_int(stock.get("acc_days", 0), 0)
    dist_days = _to_int(stock.get("dist_days", 0), 0)
    cross_age = int(stock.get("cross_age", 999))
    dist_pct = float(stock.get("dist_pct", 0))
    fresh_cross = bool(stock.get("fresh_cross", False))
    overextended = bool(stock.get("overextended", False))
    acc_days = int(stock.get("acc_days", 0))
    dist_days = int(stock.get("dist_days", 0))
    obv_dir = str(stock.get("obv_dir", "flat"))
    sector_bias = int(stock.get("sector_bias", 0))

    if cross_age == -1:
        parts.append("Bearish HMA")
    elif fresh_cross:
        parts.append(f"🟢 Cross {cross_age}d")
    elif cross_age <= 20:
        parts.append(f"Cross {cross_age}d")
    elif cross_age < 999:
        parts.append(f"⚠️ Cross {cross_age}d ago")
    else:
        parts.append("No cross")

    if overextended:
        parts.append(f"⚠️ {dist_pct:.0f}% stretched")
    elif dist_pct <= 5.0:
        parts.append(f"🟢 {dist_pct:.1f}% room")
    else:
        parts.append(f"{dist_pct:.1f}% above")

    if acc_days >= 4 and obv_dir == "rising":
        parts.append("🟢 Accum vol")
    elif dist_days >= 4 or obv_dir == "falling":
        parts.append("🔴 Dist vol")
    else:
        parts.append("Vol OK")

    if sector_bias == 1:
        parts.append("Sector ✅")
    elif sector_bias == -1:
        parts.append("Sector ❌")

    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════
# PROBABILITY HELPER
# ═══════════════════════════════════════════════════════════════


def _get_prob(stock: dict) -> dict:
    sym = stock.get("symbol", "")
    sig = get_signal(sym) if _TRACKER_OK else None

    if sig and sig.get("t1_prob", 0) > 0:
        return {
            "t1": sig["t1_prob"],
            "t2": sig["t2_prob"],
            "sl": sig["sl_prob"],
            "signal": sig,
        }

    score = float(stock.get("score", 0))
    streak = int(stock.get("streak", 0))
    cat = stock.get("category", "")
    situation = stock.get("situation", "")
    cross_age = int(stock.get("cross_age", 999))
    dist_pct = float(stock.get("dist_pct", 0))
    cat_label = CATEGORY_META.get(cat, {}).get("label", "")

    prob = calculate_probability(
        score=score,
        streak=streak,
        category=cat_label,
        situation=situation,
        cross_age=cross_age,
        dist_pct=dist_pct,
    )
    return {
        "t1": prob["t1_pct"],
        "t2": prob["t2_pct"],
        "sl": prob["sl_pct"],
        "signal": sig,
    }


# ═══════════════════════════════════════════════════════════════
# DATA: SAVE / LOAD / HISTORY
# ═══════════════════════════════════════════════════════════════


def save_scan_results(results_df, scan_date):
    if results_df.empty:
        print("No results to save")
        return

    stocks_list = []
    for idx, row in results_df.iterrows():
        entry = round(float(row.get("close", 0)), 2)
        sl = round(float(row.get("sl", entry * 0.93)), 2)
        t1 = round(float(row.get("target1", entry + (entry - sl))), 2)
        t2 = round(float(row.get("target2", entry + 2 * (entry - sl))), 2)

        streak = int(row.get("streak", 0))
        row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        situation = row_dict.get("situation", "") or assign_situation(row_dict, streak)
        trigger = row.get("entry_trigger")
        try:
            trigger = round(float(trigger), 2)
            if not math.isfinite(trigger):
                trigger = None
        except (TypeError, ValueError):
            trigger = None

        stocks_list.append(
            {
                "rank": idx + 1,
                "symbol": str(row["symbol"]),
                "score": round(float(row.get("score", 0)), 2),
                "return_1m_pct": round(float(row.get("return_1m_pct", 0)), 1),
                "return_2m_pct": round(float(row.get("return_2m_pct", 0)), 1),
                "return_3m_pct": round(float(row.get("return_3m_pct", 0)), 1),
                "return_6m_pct": round(float(row.get("return_6m_pct", 0)), 1),
                "return_12m_pct": round(float(row.get("return_12m_pct", 0)), 1),
                "close": entry,
                "volume": int(row.get("volume", 0)),
                "delivery_pct": round(float(row.get("delivery_pct", 0)), 1),
                "sl": sl,
                "target1": t1,
                "target2": t2,
                "category": str(row.get("category", "rising")),
                "streak": int(row.get("streak", 0)),
                "situation": situation,
                "cross_age": int(row.get("cross_age", 999)),
                "dist_pct": round(float(row.get("dist_pct", 0)), 1),
                "fresh_cross": bool(row.get("fresh_cross", False)),
                "overextended": bool(row.get("overextended", False)),
                "acc_days": int(row.get("acc_days", 0)),
                "dist_days": int(row.get("dist_days", 0)),
                "obv_dir": str(row.get("obv_dir", "flat")),
                "sector_bias": int(row.get("sector_bias", 0)),
                "news_tone": str(row.get("news_tone", "NEUTRAL")),
                "news_flags": str(row.get("news_flags", "")),
                "has_risk": bool(row.get("has_risk", False)),
                "horizon": str(row.get("horizon", "WATCH")),
                "action": str(row.get("action", "WATCH")),
                "entry_trigger": trigger,
                "entry_valid_until": str(row.get("entry_valid_until", "")),
                "action_reason": str(row.get("action_reason", "")),
                "lifecycle_origin": str(row.get("lifecycle_origin", "")),
                "first_seen_date": str(row.get("first_seen_date", "")),
                "stage_since": str(row.get("stage_since", "")),
                "days_tracked": int(row.get("days_tracked", 0)),
                "tv_status": str(row.get("tv_status", "NO_ENTRY")),
                "hybrid_hull_checks": row.get("hybrid_hull_checks", []),
                # Technical fields used later by the EOD model-portfolio risk check.
                "rsi": round(float(row.get("rsi", 50)), 1),
                "pts_hma": int(row.get("pts_hma", 0)),
                "pts_macd": int(row.get("pts_macd", 0)),
                "hma_trend_up": bool(row.get("hma_trend_up", False)),
                "del_trend": str(row.get("del_trend", "flat")),
                "hybrid_hull_55": round(float(row.get("hybrid_hull_55", 0)), 2),
                "hma21": round(float(row.get("hma21", 0)), 2),
                "hma51": round(float(row.get("hma51", 0)), 2),
                "atr14": round(float(row.get("atr14", 0)), 2),
                "hybrid_hull_stop": round(float(row.get("hybrid_hull_stop", 0)), 2),
                "kama30": round(float(row.get("kama30", 0)), 2),
                "daily_hull_status": str(row.get("daily_hull_status", "NOT_ALIGNED")),
                "daily_hma_aligned": bool(row.get("daily_hma_aligned", False)),
                "kama_rising": bool(row.get("kama_rising", False)),
                "weekly_hull_status": str(row.get("weekly_hull_status", "NOT_ALIGNED")),
                "weekly_hma21": round(float(row.get("weekly_hma21", 0)), 2),
                "weekly_hma51": round(float(row.get("weekly_hma51", 0)), 2),
                "hull_distance_atr": round(float(row.get("hull_distance_atr", 0)), 2),
                "hull_stretched": bool(row.get("hull_stretched", False)),
                "hull_chop": bool(row.get("hull_chop", False)),
                "hull_compression": bool(row.get("hull_compression", False)),
            }
        )

    sit_priority = {SITUATION_PRIME: 0, SITUATION_HOLD: 1, SITUATION_WATCH: 2, SITUATION_BOOK: 3, SITUATION_AVOID: 4}
    stocks_list.sort(key=lambda x: (sit_priority.get(x.get("situation", "watch"), 2), -float(x.get("score", 0))))
    for i, s in enumerate(stocks_list):
        s["rank"] = i + 1

    data = {
        "scan_date": str(scan_date),
        "total_stocks": len(stocks_list),
        "page_size": 5,
        "stocks": stocks_list,
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"✅ Scan results saved: {RESULTS_FILE}  ({len(stocks_list)} stocks)")
    save_history(stocks_list, scan_date)


def load_scan_results():
    if not os.path.exists(RESULTS_FILE):
        return None
    with open(RESULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(stocks_list, scan_date):
    today_str = str(scan_date)
    history = load_history()
    history = [h for h in history if h["date"] != today_str]
    history.append(
        {
            "date": today_str,
            "symbols": [s["symbol"] for s in stocks_list],
            "stocks": [
                {
                    "symbol": s["symbol"],
                    "score": s["score"],
                    "return_3m_pct": s["return_3m_pct"],
                    "return_1m_pct": s["return_1m_pct"],
                    "close": s["close"],
                    "sl": s["sl"],
                    "target1": s["target1"],
                    "target2": s["target2"],
                    "category": s.get("category", "rising"),
                    "situation": s.get("situation", "watch"),
                    # Kept for the Saturday digest: only a triggered BUY_TRIGGER is
                    # counted as a model trade, never a generic watch-list stock.
                    "action": s.get("action", "WATCH"),
                    "entry_trigger": s.get("entry_trigger"),
                    "entry_valid_until": s.get("entry_valid_until", ""),
                }
                for s in stocks_list
            ],
        }
    )
    history.sort(key=lambda x: x["date"], reverse=True)
    history = history[:HISTORY_DAYS]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "last_updated": today_str,
                "days_stored": len(history),
                "history": history,
            },
            f,
            indent=2,
        )


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f).get("history", [])
    except Exception:
        return []


def get_new_stocks(history):
    if len(history) < 2:
        return []
    new = set(history[0]["symbols"]) - set(history[1]["symbols"])
    return [s for s in history[0]["stocks"] if s["symbol"] in new]


def get_exit_stocks(history):
    if len(history) < 2:
        return []
    exits = set(history[1]["symbols"]) - set(history[0]["symbols"])
    return [s for s in history[1]["stocks"] if s["symbol"] in exits]


def get_strong_stocks(history, min_days=5):
    if not history:
        return []
    strong = []
    for symbol in set(history[0]["symbols"]):
        n = 0
        for day in history:
            if symbol in day["symbols"]:
                n += 1
            else:
                break
        if n >= min_days:
            sd = next((s for s in history[0]["stocks"] if s["symbol"] == symbol), None)
            if sd:
                strong.append({**sd, "consecutive_days": n})
    strong.sort(key=lambda x: x["consecutive_days"], reverse=True)
    return strong


def get_caution_stocks(stocks):
    caution = []
    for s in stocks:
        score = float(s.get("score", 10))
        delivery = float(s.get("delivery_pct", 100))
        r3m = float(s.get("return_3m_pct", 0))
        dist_pct = float(s.get("dist_pct", 0))
        situation = s.get("situation", "watch")

        if score <= 5 or delivery < 40 or r3m > 40 or dist_pct > 15 or situation in (SITUATION_AVOID, SITUATION_BOOK):
            caution.append(s)
    return caution


def get_stock_streak(symbol, history):
    n = 0
    for day in history:
        if symbol in day["symbols"]:
            n += 1
        else:
            break
    return n


# ═══════════════════════════════════════════════════════════════
# SORTING
# ═══════════════════════════════════════════════════════════════


def sort_stocks(stocks, mode="score"):
    sit_priority = {
        SITUATION_PRIME: 0,
        SITUATION_HOLD: 1,
        SITUATION_WATCH: 2,
        SITUATION_BOOK: 3,
        SITUATION_AVOID: 4,
    }

    if mode == "score":
        return sorted(
            stocks, key=lambda x: (sit_priority.get(x.get("situation", "watch"), 2), -float(x.get("score", 0)))
        )
    if mode == "3m":
        return sorted(stocks, key=lambda x: float(x.get("return_3m_pct", 0)), reverse=True)
    if mode == "top10":
        return sorted(stocks, key=lambda x: float(x.get("score", 0)), reverse=True)[:10]
    if mode == "prime":
        return [s for s in stocks if s.get("situation") == SITUATION_PRIME]
    return sorted(stocks, key=lambda x: float(x.get("score", 0)), reverse=True)


# ═══════════════════════════════════════════════════════════════
# NEWS
# ═══════════════════════════════════════════════════════════════


def fetch_news_for_symbol(symbol, max_items=3):
    try:
        news_file = os.path.join(_HERE, "output", "news_latest.json")
        if not os.path.exists(news_file):
            today_str = date.today().strftime("%d%m%Y")
            news_file = os.path.join(_HERE, "output", f"news_{today_str}.json")

        if os.path.exists(news_file):
            with open(news_file, encoding="utf-8") as f:
                collected = json.load(f)
                if symbol in collected:
                    data = collected[symbol]
                    combined = []
                    for ann in data.get("announcements", []):
                        combined.append({"title": ann.get("subject", ""), "date": ann.get("date", "")[:10]})
                    for hl in data.get("headlines", []):
                        combined.append({"title": hl.get("title", ""), "date": hl.get("date", "")})
                    if combined:
                        return combined[:max_items]
    except Exception:
        pass

    try:
        from xml.etree import ElementTree as ET

        import requests

        url = (
            f"https://news.google.com/rss/search?q={symbol}"
            f"+stock+news+Moneycontrol+Economic+Times&hl=en-IN&gl=IN&ceid=IN:en"
        )
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        news = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").split(" - ")[0].strip()
            pub = item.findtext("pubDate", "")
            try:
                pub_fmt = datetime.strptime(pub[:16], "%a, %d %b %Y").strftime("%d-%b")
            except Exception:
                pub_fmt = pub[:10]
            news.append({"title": title, "date": pub_fmt})
        return news
    except Exception:
        return []


def format_news_block(news):
    if not news:
        return f"   {_i('No recent news')}\n"
    return "".join(f"   📰 {_h(n['title'][:80])} {_i('(' + n['date'] + ')')}\n" for n in news)


# ═══════════════════════════════════════════════════════════════
# STOCK CARD
# ═══════════════════════════════════════════════════════════════


def _stock_card(stock, rank=0, show_prob=True, show_frozen=False, show_signal=True):
    e = float(stock.get("close", 0))
    sl = float(stock.get("sl", e * 0.93))
    t1 = float(stock.get("target1", e + (e - sl)))
    t2 = float(stock.get("target2", e + 2 * (e - sl)))
    r3 = float(stock.get("return_3m_pct", 0))
    sc = round(float(stock.get("score", 0)))
    st = int(stock.get("streak", 0))
    sit = stock.get("situation", SITUATION_WATCH)
    horizon = stock.get("horizon", "WATCH")
    action = stock.get("action", "WATCH").replace("_", " ")

    sm = SITUATION_META.get(sit, SITUATION_META.get("watch", {}))
    sit_icon = sm.get("icon", "•")

    prefix = f"{_b(str(rank) + '.')} " if rank else ""
    stag = f"  🔥{st}d" if st >= 5 else ""

    msg = f"{prefix}{_code(stock['symbol'])}  {sc}/10{stag}  {sit_icon}\n"
    msg += f"   {_b(str(horizon))} | {_b(str(action))}\n"
    if stock.get("days_tracked", 0):
        msg += f"   Tracked {stock.get('days_tracked')} scan day(s) since {stock.get('first_seen_date', '')}\n"

    if show_frozen and _TRACKER_OK:
        sig = get_signal(stock["symbol"])
        if sig and sig.get("entry_price", 0) > 0:
            fe = sig["entry_price"]
            fd = sig.get("entry_date", "?")[:10]
            msg += f"   Entry(frozen {fd}) {_fmt_price(fe)} | Now {_fmt_price(e)}\n"
            msg += f"   P/L {_fmt_pl(fe, e)}\n"

    msg += f"   Entry {_fmt_price(e)} | SL {_fmt_price(sl)}\n"
    msg += f"   T1 {_fmt_price(t1)} | T2 {_fmt_price(t2)}"

    trigger = stock.get("entry_trigger")
    if trigger:
        msg += f"\n   Buy only above {_fmt_price(trigger)} (valid {stock.get('entry_valid_until', '')})"
    checks = stock.get("hybrid_hull_checks", [])
    if checks:
        msg += f"\n   {_b('Hybrid Hull:')} {_i(stock.get('tv_status', 'NO_ENTRY').replace('_', ' '))}"
        for check in checks[:3]:
            msg += f"\n   • {_i(check)}"

    if show_prob:
        p = _get_prob(stock)
        if p["t1"] > 0:
            msg += f"  ·  T1 {p['t1']}% T2 {p['t2']}%"
    msg += "\n"

    if show_signal and any(k in stock for k in ["cross_age", "dist_pct", "acc_days"]):
        sig_line = get_situation_signal_line(stock)
        if sig_line:
            msg += f"   {_i(sig_line)}\n"

    msg += f"   3M {_fmt_return(r3)} {_i('(ref)')}\n"

    nt = stock.get("news_tone", "NEUTRAL")
    nf = stock.get("news_flags", "")
    hr = stock.get("has_risk", False)
    if nt == "POSITIVE":
        msg += f"   🔥 {_i('News: Positive sentiment detected')}\n"
    elif hr or nt == "NEGATIVE":
        msg += f"   🛑 {_b('RISK:')} {_i(nf or 'Negative news or regulatory alert')}\n"

    return msg


# Plain-English wording used in the daily Telegram report.  The scanner's
# internal labels stay in the saved JSON, but the reader should not need to
# understand them before deciding whether to act.
HORIZON_PLAIN = {
    "NEW_1M_SETUP": "New short-term opportunity (about 1 month)",
    "CARRY_1_3M": "Healthy trend being carried (1 to 3 months)",
    "CARRY_3_6M": "Established medium-term trend (3 to 6 months)",
    "DIRECT_3M": "Established 3-month trend",
    "DIRECT_6M": "Established 6-month trend",
    "CORE_12M": "Long-term market leader (6 to 12 months)",
}

ACTION_PLAIN = {
    "BUY_TRIGGER": "Buy only after the trigger price is crossed",
    "WAIT_PULLBACK": "Wait for a better entry price",
    "HOLD_TRAIL": "Hold if owned; raise the stop as price rises",
    "PARTIAL_PROFIT": "Book some profit; protect the balance",
    "EXIT_ALERT": "Exit or reduce the position",
    "WATCH": "Watch only; do not buy today",
    "AVOID": "Avoid today",
}


def _plain_horizon(stock):
    return HORIZON_PLAIN.get(stock.get("horizon"), "Trend under observation")


def _plain_action(stock):
    return ACTION_PLAIN.get(stock.get("action"), "Watch only; do not buy today")


def _plain_stock_card(stock, rank=0, mode="buy"):
    """A readable action card for the daily report, not a technical dashboard."""
    symbol = stock.get("symbol", "UNKNOWN")
    close = float(stock.get("close", 0))
    sl = float(stock.get("sl", close * 0.93))
    t1 = float(stock.get("target1", close + (close - sl)))
    t2 = float(stock.get("target2", close + 2 * (close - sl)))
    action = stock.get("action", "WATCH")
    prefix = f"{_b(str(rank) + '.')} " if rank else ""

    if mode == "buy":
        trigger = float(stock.get("entry_trigger") or close)
        valid = stock.get("entry_valid_until", "")
        msg = f"{prefix}{_code(symbol)} — {_b('BUY ONLY ABOVE ' + _fmt_price(trigger))}\n"
        msg += f"   Why it is here: {_plain_horizon(stock)}\n"
        msg += "   Entry window: next 2 trading sessions"
        if valid:
            msg += f" (until {_h(valid)})"
        msg += "\n"
        msg += f"   Safety stop: exit below {_b(_fmt_price(sl))}\n"
        msg += f"   Profit plan: first {_fmt_price(t1)}  |  final {_fmt_price(t2)}\n"
        msg += "   Before buying: confirm Daily + Weekly Hybrid Hull are green; no conflict.\n"
    elif mode == "manage":
        verb = "BOOK SOME PROFIT" if action == "PARTIAL_PROFIT" else "HOLD, BUT PROTECT PROFIT"
        if action == "EXIT_ALERT":
            verb = "EXIT OR REDUCE NOW"
        msg = f"{prefix}{_code(symbol)} — {_b(verb)}\n"
        msg += f"   Trend: {_plain_horizon(stock)}\n"
        msg += f"   Protection level: {_b(_fmt_price(sl))}\n"
        msg += f"   Next levels: {_fmt_price(t1)}  |  {_fmt_price(t2)}\n"
        msg += "   Check Hybrid Hull before taking any fresh action.\n"
    else:
        msg = f"{prefix}{_code(symbol)} — {_b(_plain_action(stock))}\n"
        msg += f"   Trend: {_plain_horizon(stock)} | Last close: {_fmt_price(close)}\n"
        if action == "WAIT_PULLBACK":
            msg += f"   Do not chase price. Re-check near the safety level {_fmt_price(sl)}.\n"
        else:
            msg += "   Keep it on the watchlist; no new trade today.\n"

    reason = stock.get("action_reason")
    if reason:
        msg += f"   {_i(str(reason))}\n"
    return msg


def _compact_action_line(stock):
    """One-line status for a stock that needs no immediate trade."""
    symbol = _code(stock.get("symbol", "UNKNOWN"))
    close = _fmt_price(stock.get("close", 0))
    action = stock.get("action", "WATCH")
    if action in ("HOLD_TRAIL", "PARTIAL_PROFIT", "EXIT_ALERT"):
        return f"   {symbol}: {_plain_action(stock)} | protect below {_b(_fmt_price(stock.get('sl', 0)))}\n"
    return f"   {symbol}: {_plain_action(stock)} | last close {close}\n"


# ═══════════════════════════════════════════════════════════════
# FORMAT: WELCOME
# ═══════════════════════════════════════════════════════════════


def format_welcome(user_name=None):
    name = user_name or ""
    try:
        from nse_output import format_welcome_scan

        msg, _ = format_welcome_scan(name)
        return msg
    except Exception:
        pass

    greeting = f"👋 {_b('Hello' + (' ' + _h(name) if name else '') + '!')}\n\n"
    res = load_scan_results()
    if res and res.get("stocks"):
        stocks = res["stocks"]
        ds = _date_str(res.get("scan_date", ""))
        sit_counts = {}
        for s in stocks:
            sit = s.get("situation", SITUATION_WATCH)
            sit_counts[sit] = sit_counts.get(sit, 0) + 1
        prime = sit_counts.get(SITUATION_PRIME, 0)
        parts = []
        for sit in SITUATION_ORDER:
            if sit in sit_counts:
                sm = SITUATION_META.get(sit, {})
                parts.append(f"{sm.get('icon', '·')} {sit_counts[sit]}")
        return (
            greeting
            + f"📊 {_b('NSE Scan — ' + ds)}\n"
            + f"{len(stocks)} stocks · "
            + " · ".join(parts)
            + "\n\n"
            + (f"🎯 {_b(str(prime) + ' Prime Entry stock(s) today!')}\n\n" if prime > 0 else "")
            + f"{_i('Tap 🎯 Prime below for entry-ready stocks')}"
        )

    return (
        greeting
        + f"📊 {_b('NSE Scanner Daily')}\n\n"
        + f"{_i('Scan data not available yet.')}\n"
        + "Pipeline runs at 6:00 AM IST daily."
    )


# ═══════════════════════════════════════════════════════════════
# FORMAT: TODAY SCAN
# ═══════════════════════════════════════════════════════════════


def format_today_scan(stocks, scan_date=None):
    ds = _date_str(scan_date)

    groups = {
        key: []
        for key in ("BUY_TRIGGER", "WAIT_PULLBACK", "HOLD_TRAIL", "PARTIAL_PROFIT", "EXIT_ALERT", "WATCH", "AVOID")
    }
    for stock in stocks:
        groups.setdefault(stock.get("action", "WATCH"), []).append(stock)

    buy = groups["BUY_TRIGGER"]
    wait = groups["WAIT_PULLBACK"] + groups["WATCH"]
    manage = groups["HOLD_TRAIL"] + groups["PARTIAL_PROFIT"] + groups["EXIT_ALERT"]
    avoid = groups["AVOID"]

    msg = f"📌 {_b('Today’s trading plan — ' + ds)}\n"
    msg += f"{_i('Built from the previous market close. A scan is research, not a promise of profit.')}\n\n"
    msg += (
        f"✅ Buy today: {_b(str(len(buy)))}  |  👀 Wait: {_b(str(len(wait)))}  |  "
        f"🛡️ Manage: {_b(str(len(manage)))}  |  🚫 Avoid: {_b(str(len(avoid)))}\n"
    )
    msg += SEP_THIN + "\n\n"

    if buy:
        msg += f"✅ {_b('ACT TODAY — only after the trigger is crossed')}\n"
        msg += f"{_i('Choose at most one or two. Do not buy before the stated price.')}\n\n"
        for rank, stock in enumerate(buy[:5], 1):
            msg += _plain_stock_card(stock, rank=rank, mode="buy") + "\n"
        if len(buy) > 5:
            msg += f"   {_i(str(len(buy) - 5) + ' more buy setups are available in the Buy Setups menu.')}\n\n"

    if wait:
        msg += f"👀 {_b('GOOD STOCKS — WAIT, DO NOT CHASE')}\n"
        msg += f"{_i('These are on the radar but are not fresh buys today.')}\n"
        for stock in wait:
            msg += _compact_action_line(stock)
        msg += "\n"

    if manage:
        msg += f"🛡️ {_b('IF YOU ALREADY OWN THESE')}\n"
        for stock in manage:
            msg += _compact_action_line(stock)
        msg += "\n"

    if avoid:
        msg += f"🚫 {_b('AVOID TODAY')}\n"
        msg += "   " + ", ".join(_code(s.get("symbol", "?")) for s in avoid) + "\n\n"

    msg += SEP_THIN + "\n"
    msg += f"{_b('Simple rule:')} Buy only after price crosses the trigger; always respect the safety stop.\n"
    msg += f"{_i('Final check: TradingView Hybrid Hull must show Daily + Weekly alignment before entry.')}"
    return msg

    sit_groups = {}
    for s in stocks:
        streak = int(s.get("streak", 0))
        sit = s.get("situation") or assign_situation(s, streak)
        sit_groups.setdefault(sit, []).append({**s, "situation": sit})

    parts = []
    for sit in SITUATION_ORDER:
        if sit in sit_groups:
            sm = SITUATION_META.get(sit, {})
            parts.append(f"{sm.get('icon', '·')} {len(sit_groups[sit])} {sm.get('label', '').split()[0].lower()}")

    msg = f"📊 {_b('NSE Daily Scan — ' + ds)}\n"
    msg += f"{_i('Ranked by forward probability score')}\n\n"
    msg += " · ".join(parts) + "\n"
    msg += SEP_THIN + "\n\n"

    rank = 1
    for sit in SITUATION_ORDER:
        group = sit_groups.get(sit, [])
        if not group:
            continue
        sm = SITUATION_META.get(sit, {})
        msg += f"{sm.get('icon', '')} {_b(sm.get('label', sit.title()))} ({len(group)})\n"
        msg += f"   {_i(sm.get('action', ''))}\n\n"

        if sit in (SITUATION_PRIME, SITUATION_HOLD):
            for s in group:
                msg += _stock_card(s, rank=rank, show_prob=True, show_frozen=(sit == SITUATION_HOLD), show_signal=True)
                msg += "\n"
                rank += 1
        else:
            for s in group:
                sc = round(float(s.get("score", 0)))
                e = float(s.get("close", 0))
                float(s.get("return_3m_pct", 0))
                cross = int(s.get("cross_age", 999))
                cross_str = f"cross {cross}d" if 0 < cross < 999 else "no cross" if cross == 999 else "bearish"
                msg += (
                    f"{_b(str(rank) + '.')} {_code(s['symbol'])}  {sc}/10"
                    f"  {_fmt_price(e)}  {_i(cross_str)}\n"
                    f"   {_b(str(s.get('horizon', 'WATCH')))} | "
                    f"{_b(str(s.get('action', 'WATCH')).replace('_', ' '))}\n"
                )
                rank += 1
            msg += "\n"

    if _TRACKER_OK:
        ts = get_tracker_summary()
        if ts.get("avg_t1_prob", 0) > 0:
            msg += SEP_THIN + "\n"
            msg += (
                f"{_b('Probability outlook')}\n"
                f"Avg T1: {ts['avg_t1_prob']}% · "
                f"Avg T2: {ts['avg_t2_prob']}% · "
                f"T1>70%: {_b(str(ts.get('high_prob_count', 0)))} stocks\n"
            )

    msg += SEP_THIN + "\n"
    msg += f"{_i('Tap Prime for entry-ready stocks · TV confirms timing')}"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: PRIME
# ═══════════════════════════════════════════════════════════════


def format_prime_stocks(stocks, scan_date=None):
    ds = _date_str(scan_date)

    buy_setups = [stock for stock in stocks if stock.get("action") == "BUY_TRIGGER"]
    if not buy_setups:
        return (
            f"✅ {_b('Buy setups — ' + ds)}\n\n"
            f"{_i('No fresh buy setup today.')}\n\n"
            "Do not force a trade. Check the waiting list or review existing holdings."
        )

    msg = f"✅ {_b('Buy setups — ' + ds)}\n"
    msg += f"{_i('Buy only when the trigger is crossed and TradingView confirms the trend.')}\n"
    msg += SEP_THIN + "\n\n"
    for rank, stock in enumerate(buy_setups[:8], 1):
        msg += _plain_stock_card(stock, rank=rank, mode="buy") + "\n"
    msg += SEP_THIN + "\n"
    if len(buy_setups) > 8:
        msg += f"Showing the top 8 of {len(buy_setups)} setups. Focus on the best one or two; do not overtrade."
    elif len(buy_setups) == 1:
        msg += "1 setup today. Quality over quantity."
    else:
        msg += f"{len(buy_setups)} buy setups. Focus on the best one or two; do not overtrade."
    return msg

    prime = []
    for s in stocks:
        streak = int(s.get("streak", 0))
        sit = s.get("situation") or assign_situation(s, streak)
        if sit == SITUATION_PRIME:
            prime.append({**s, "situation": sit})

    if not prime:
        return (
            f"🎯 {_b('Prime Entry — ' + ds)}\n\n"
            f"{_i('No PRIME ENTRY stocks today')}\n\n"
            f"This means:\n"
            f"• No fresh HMA crosses (≤10 days)\n"
            f"• Or all good stocks are overextended\n"
            f"• Or volume not confirming\n\n"
            f"Check {_b('Watch Closely')} for stocks to monitor.\n"
            f"Market may be in consolidation — patience pays."
        )

    msg = f"🎯 {_b('Prime Entry — ' + ds)}\n"
    msg += f"{_i('Best forward probability setups today')}\n"
    msg += f"{_i('Confirm each on TradingView before entering')}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(prime, 1):
        msg += _stock_card(s, rank=i, show_prob=True, show_frozen=False, show_signal=True)
        msg += f"   {_b('TV Check:')}\n"
        msg += "   Regime TREND ✓ · ADX ≥20 ✓ · W.Trend Bull ✓\n\n"

    msg += SEP_THIN + "\n"
    if len(prime) == 1:
        msg += "1 high-probability setup today · Quality over quantity"
    else:
        msg += f"{len(prime)} high-probability setups · Focus on top 1-2 · Don't overtrade"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: STOCK LIST (paginated)
# ═══════════════════════════════════════════════════════════════


def format_stock_list(stocks, start_idx=0, count=5, scan_date=None, include_news=False):
    end = min(start_idx + count, len(stocks))
    sel = stocks[start_idx:end]
    cp = (start_idx // count) + 1
    tp = max(1, (len(stocks) + count - 1) // count)
    ds = _date_str(scan_date)

    msg = f"📊 {_b('Watchlist — ' + ds)}\n"
    msg += f"{_i('Sorted by forward score · Page ' + str(cp) + '/' + str(tp))}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(sel, start=start_idx + 1):
        msg += _stock_card(s, rank=i, show_prob=True, show_signal=True)
        if include_news:
            msg += format_news_block(fetch_news_for_symbol(s["symbol"]))
        msg += "\n"

    msg += SEP_THIN + "\n"
    msg += f"Page {cp}/{tp}"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: NEW ENTRIES
# ═══════════════════════════════════════════════════════════════


def format_new_stocks(new_stocks, scan_date=None):
    ds = _date_str(scan_date)

    if not new_stocks:
        return (
            f"🆕 {_b('New entries — ' + ds)}\n\n"
            f"{_i('No new stocks entered today')}\n\n"
            f"All 25 carried over from yesterday — consistency!"
        )

    msg = f"🆕 {_b('New entries — ' + ds)}\n"
    msg += f"{_i(str(len(new_stocks)) + ' stock(s) entered top 25 today')}\n"
    msg += f"{_i('Fresh signals — check situation before entering')}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(new_stocks, 1):
        streak = int(s.get("streak", 0))
        sit = s.get("situation") or assign_situation(s, streak)
        sm = SITUATION_META.get(sit, SITUATION_META.get("watch", {}))
        e = float(s.get("close", 0))
        sl = float(s.get("sl", e * 0.93))
        t1 = float(s.get("target1", e + (e - sl)))
        t2 = float(s.get("target2", e + 2 * (e - sl)))
        r3 = float(s.get("return_3m_pct", 0))
        sc = round(float(s.get("score", 0)))
        p = _get_prob(s)

        msg += f"{_b(str(i) + '.')} {_code(s['symbol'])}  {sc}/10  🆕  {sm.get('icon', '')} {_i(sm.get('label', ''))}\n"
        msg += f"   Entry {_fmt_price(e)} | SL {_fmt_price(sl)}\n"
        msg += f"   T1 {_fmt_price(t1)} | T2 {_fmt_price(t2)} | 3M {_fmt_return(r3)}\n"
        if p["t1"] > 0:
            msg += f"   T1 {p['t1']}% · T2 {p['t2']}%\n"
        sig_line = get_situation_signal_line(s)
        if sig_line:
            msg += f"   {_i(sig_line)}\n"
        msg += "\n"

    msg += SEP_THIN + "\n"
    msg += f"{len(new_stocks)} new stock(s) entered today"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: EXIT
# ═══════════════════════════════════════════════════════════════


def format_exit_stocks(exit_stocks, scan_date=None):
    ds = _date_str(scan_date)

    if not exit_stocks:
        return (
            f"📉 {_b('Exit watch — ' + ds)}\n\n"
            f"{_i('No stocks exited today')}\n\n"
            f"Yesterday's list intact — momentum holding!"
        )

    msg = f"📉 {_b('Exit watch — ' + ds)}\n"
    msg += f"{_i('Dropped out — consider booking profits')}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(exit_stocks, 1):
        sc = round(float(s.get("score", 0)))
        e = float(s.get("close", 0))
        r3 = float(s.get("return_3m_pct", 0))

        msg += f"{_b(str(i) + '.')} {_code(s['symbol'])}  was {sc}/10  [Exited]\n"

        if _TRACKER_OK:
            sig = get_signal(s["symbol"])
            if sig and sig.get("entry_price", 0) > 0:
                fe = sig["entry_price"]
                days = sig.get("days_in_list", sig.get("streak", 0))
                t1h = "T1 was hit ✅" if sig.get("t1_hit_date") else "T1 not hit"
                msg += f"   Was in list {days} days\n"
                msg += f"   Entry {_fmt_price(fe)} → Exit {_fmt_price(e)}\n"
                msg += f"   Final P/L: {_fmt_pl(fe, e)} | {t1h}\n"
            else:
                msg += f"   Last price {_fmt_price(e)} | 3M {_fmt_return(r3)}\n"
        else:
            msg += f"   Last price {_fmt_price(e)} | 3M {_fmt_return(r3)}\n"

        if _TRACKER_OK:
            sig = get_signal(s["symbol"])
            if sig and sig.get("t1_hit_date"):
                msg += f"   {_i('Profit booked — well played')}\n"
            else:
                msg += f"   {_i('Consider tightening stop loss')}\n"
        else:
            msg += f"   {_i('Consider tightening stop loss')}\n"
        msg += "\n"

    msg += SEP_THIN + "\n"
    msg += f"{len(exit_stocks)} stock(s) dropped out today"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: CAUTION
# ═══════════════════════════════════════════════════════════════


def format_caution_stocks(stocks, scan_date=None):
    ds = _date_str(scan_date)
    caution = get_caution_stocks(stocks)

    if not caution:
        return f"⚠️ {_b('Caution flags — ' + ds)}\n\n{_i('No caution flags — all stocks looking solid!')}"

    msg = f"⚠️ {_b('Caution & Avoid — ' + ds)}\n"
    msg += f"{_i('These need extra care or should be skipped')}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(caution, 1):
        sc = round(float(s.get("score", 0)))
        dl = float(s.get("delivery_pct", 0))
        e = float(s.get("close", 0))
        r3 = float(s.get("return_3m_pct", 0))
        sit = s.get("situation", "")
        dist_pct = float(s.get("dist_pct", 0))
        cross_age = int(s.get("cross_age", 0))
        p = _get_prob(s)

        reasons = []
        if sit == SITUATION_AVOID:
            reasons.append("Avoid — weak signal or distribution")
        elif sit == SITUATION_BOOK:
            reasons.append("Book profits — move is maturing")
        if sc <= 5:
            reasons.append(f"Low score {sc}/10")
        if dl < 40:
            reasons.append(f"Low delivery {dl:.0f}%")
        if r3 > 40:
            reasons.append(f"Overextended ({_fmt_return(r3)})")
        if dist_pct > 15:
            reasons.append(f"{dist_pct:.0f}% above HMA55")
        if cross_age > 30:
            reasons.append(f"Cross {cross_age}d ago — mature")

        sit_icon = SITUATION_META.get(sit, {}).get("icon", "⚠️")
        state_tag = "Avoid" if sit == SITUATION_AVOID else ("Book" if sit == SITUATION_BOOK else "Risk")

        msg += f"{_b(str(i) + '.')} {_code(s['symbol'])}  {sc}/10  [{state_tag}] {sit_icon}\n"
        msg += f"   Price {_fmt_price(e)} | 3M {_fmt_return(r3)}\n"

        if p["t1"] > 0:
            msg += f"   T1 prob: {p['t1']}% · SL risk: {p['sl']}%\n"

        msg += f"   ⚠️ {' | '.join(reasons)}\n"

        if sit == SITUATION_AVOID:
            msg += f"   {_i('Skip this trade — below quality threshold')}\n"
        elif sit == SITUATION_BOOK:
            msg += f"   {_i('Consider booking 50-100% profits')}\n"
        elif p["sl"] >= 35:
            msg += f"   {_i('High SL risk — tighten stop or book profits')}\n"
        msg += "\n"

    msg += SEP_THIN + "\n"
    msg += f"{len(caution)} stock(s) need extra caution"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: STRONG / HOLD AND TRAIL
# ═══════════════════════════════════════════════════════════════


def format_strong_stocks(strong_stocks, scan_date=None):
    ds = _date_str(scan_date)

    if not strong_stocks:
        return (
            f"💰 {_b('Hold & Trail — ' + ds)}\n\n"
            f"{_i('No stocks in top 25 for 5+ days yet')}\n\n"
            f"Building history — check back soon."
        )

    msg = f"💰 {_b('Hold & Trail — ' + ds)}\n"
    msg += f"{_i('In top 25 for 5+ consecutive days')}\n"
    msg += f"{_i('Sustained momentum — trail your stop loss')}\n"
    msg += SEP_THIN + "\n\n"

    for i, s in enumerate(strong_stocks, 1):
        e = float(s.get("close", 0))
        sl = float(s.get("sl", e * 0.93))
        t1 = float(s.get("target1", e + (e - sl)))
        t2 = float(s.get("target2", e + 2 * (e - sl)))
        float(s.get("return_3m_pct", 0))
        sc = round(float(s.get("score", 0)))
        dy = s.get("consecutive_days", 0)
        sit = s.get("situation", SITUATION_HOLD)
        sm = SITUATION_META.get(sit, SITUATION_META.get("hold", {}))

        msg += f"{_b(str(i) + '.')} {_code(s['symbol'])}  {sc}/10  {dy}d streak  💰\n"
        msg += f"   {sm.get('icon', '')} {_i(sm.get('label', 'Hold & Trail'))}\n"

        if _TRACKER_OK:
            sig = get_signal(s["symbol"])
            if sig and sig.get("entry_price", 0) > 0:
                fe = sig["entry_price"]
                fd = sig.get("entry_date", "?")[:10]
                t1h = sig.get("t1_hit_date")
                msg += f"   Entry(frozen {fd}) {_fmt_price(fe)} | Now {_fmt_price(e)}\n"
                msg += f"   P/L {_fmt_pl(fe, e)}"
                if t1h:
                    msg += "  · T1 hit ✅ → SL at entry"
                msg += "\n"

        msg += f"   SL {_fmt_price(sl)} | T1 {_fmt_price(t1)} | T2 {_fmt_price(t2)}\n"

        p = _get_prob(s)
        if p["t1"] > 0:
            msg += f"   T1 {p['t1']}% · T2 {p['t2']}%\n"
        msg += "\n"

    msg += SEP_THIN + "\n"
    msg += f"{len(strong_stocks)} stock(s) with sustained momentum"
    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: SUMMARY
# ═══════════════════════════════════════════════════════════════


def format_summary(stocks, scan_date=None, history=None):
    ds = _date_str(scan_date)

    sit_counts = {}
    for s in stocks:
        sit = s.get("situation", SITUATION_WATCH)
        sit_counts[sit] = sit_counts.get(sit, 0) + 1

    avg_score = sum(float(s.get("score", 0)) for s in stocks) / max(len(stocks), 1)

    msg = f"📊 {_b('Daily summary — ' + ds)}\n"
    msg += SEP_BOLD + "\n"
    msg += f"Total: {_b(str(len(stocks)))} stocks · Avg score: {_b(str(round(avg_score, 1)))}\n"

    if history and len(history) >= 2:
        new_count = len(get_new_stocks(history))
        exit_count = len(get_exit_stocks(history))
        msg += f"New today: {new_count} · Exited: {exit_count}\n"

    msg += SEP_THIN + "\n"
    msg += f"{_b('Situation breakdown')}\n"
    for sit in SITUATION_ORDER:
        if sit in sit_counts:
            sm = SITUATION_META.get(sit, {})
            msg += f"{sm.get('icon', '')} {sm.get('label', sit.title())}: {sit_counts[sit]} stocks\n"

    prime_count = sit_counts.get(SITUATION_PRIME, 0)
    if prime_count > 0:
        prime_stocks = [s["symbol"] for s in stocks if s.get("situation") == SITUATION_PRIME]
        msg += f"\n🎯 {_b('Prime entry today:')} {', '.join(prime_stocks)}\n"

    msg += SEP_THIN + "\n"
    msg += f"{_b('Top 5 by forward score')}\n"
    top5 = sorted(stocks, key=lambda x: float(x.get("score", 0)), reverse=True)[:5]
    for j, s in enumerate(top5, 1):
        sc = round(float(s.get("score", 0)))
        sit = s.get("situation", "")
        sm = SITUATION_META.get(sit, {})
        msg += f"{j}. {_code(s['symbol'])} {sc}/10 {sm.get('icon', '')}\n"

    if _TRACKER_OK:
        ts = get_tracker_summary()
        if ts.get("avg_t1_prob", 0) > 0:
            msg += SEP_THIN + "\n"
            msg += f"{_b('Probability outlook')}\n"
            msg += (
                f"Avg T1: {ts['avg_t1_prob']}% · "
                f"Avg T2: {ts['avg_t2_prob']}% · "
                f"T1>70%: {_b(str(ts.get('high_prob_count', 0)))} "
                f"of {ts.get('total_active', 0)}\n"
            )

    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT: PORTFOLIO COMMANDS (v6.1 — new)
# ═══════════════════════════════════════════════════════════════


def format_portfolio():
    """For /portfolio command — open positions with live P/L."""
    try:
        from nse_portfolio import format_portfolio_for_bot

        return format_portfolio_for_bot()
    except ImportError:
        return _i("nse_portfolio.py not found. Deploy it first.")
    except Exception as e:
        return _i(f"Portfolio error: {e}")


def format_exits():
    """For /exits command — closed trade history."""
    try:
        from nse_portfolio import format_exits_for_bot

        return format_exits_for_bot(last_n=15)
    except ImportError:
        return _i("nse_portfolio.py not found. Deploy it first.")
    except Exception as e:
        return _i(f"Exits error: {e}")


def format_returns():
    """For /returns command — portfolio summary stats."""
    try:
        from nse_portfolio import get_open_positions, get_portfolio_summary

        s = get_portfolio_summary()
        pos = get_open_positions()

        msg = f"📈 {_b('Portfolio Returns')}\n"
        msg += f"{SEP_THIN}\n"
        msg += f"Open positions : {s['open_count']}\n"
        msg += f"Closed trades  : {s['closed_count']}\n"
        msg += f"Win rate       : {_b(str(s['win_rate']) + '%')}\n"
        msg += f"Last run       : {s['last_run'][:10] if s['last_run'] else 'Never'}\n\n"

        tiers = s.get("tiers", {})
        if any(tiers.values()):
            msg += f"{_b('Tiers')}\n"
            msg += f"  🏆 Conviction : {tiers.get('Conviction', 0)}\n"
            msg += f"  📈 Compounder : {tiers.get('Compounder', 0)}\n"
            msg += f"  🌱 Building   : {tiers.get('Building', 0)}\n\n"

        if pos:
            total_pl = 0
            winners = 0
            for p in pos.values():
                entry = float(p.get("entry_price", 0))
                current = float(p.get("current_price", entry))
                if entry > 0:
                    pl = (current - entry) / entry * 100
                    total_pl += pl
                    if pl >= 0:
                        winners += 1
            avg_pl = total_pl / len(pos)
            pl_sign = "+" if avg_pl >= 0 else ""
            msg += f"{_b('Open P/L Avg')}: {pl_sign}{avg_pl:.1f}%\n"
            msg += f"Winners: {winners} / {len(pos)}\n"

        return msg
    except ImportError:
        return _i("nse_portfolio.py not found. Deploy it first.")
    except Exception as e:
        return _i(f"Returns error: {e}")


# ═══════════════════════════════════════════════════════════════
# FORMAT: HELP
# ═══════════════════════════════════════════════════════════════


def format_help():
    return (
        f"🤖 {_b('NSE Momentum Scanner Bot')}\n\n"
        f"{_b('Situation Views:')}\n"
        f"🎯 /prime — Stocks ready to enter today\n"
        f"📊 /today — Full scan grouped by situation\n"
        f"🆕 /new — New stocks entered today\n"
        f"📉 /exit — Stocks removed today\n"
        f"⚠️ /caution — Caution + avoid signals\n"
        f"💰 /strong — 5+ day streak (hold & trail)\n"
        f"📅 /digest — Last week performance\n"
        f"📖 /guide — How to read the scanner\n\n"
        f"{_b('Portfolio:')}\n"
        f"💼 /portfolio — Open positions + live P/L\n"
        f"📊 /returns — Win rate + performance stats\n"
        f"📉 /exits — Closed trade history\n\n"
        f"{_b('Situations explained:')}\n"
        f"🎯 Prime — Fresh cross, room to run, accum vol\n"
        f"💰 Hold — In move 5+ days, trail your SL\n"
        f"👀 Watch — Good setup, one signal missing\n"
        f"⚠️ Book — Move mature, protect profits\n"
        f"🚫 Avoid — Weak/bearish, skip today\n\n"
        f"{_b('Navigation:')}\n"
        f"/start — Welcome menu\n"
        f"/list — Flat ranked list\n"
        f"/next /prev — Paginate\n"
        f"/news — Page with headlines\n"
        f"/help — This message\n\n"
        f"{_b('Sort options:')}\n"
        f"Score — By forward probability score\n"
        f"3M — By 3-month return (reference)\n"
        f"Top10 — Top 10 by score\n\n"
        f"{_b('Admin (owner only):')}\n"
        f"/admin — Health check dashboard\n"
        f"/users — Bot user list\n\n"
        f"{_i('Tap buttons to navigate!')}"
    )


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.test:
        import pandas as pd

        df = pd.DataFrame(
            {
                "symbol": ["KAYNES", "DIXON", "SYRMA", "EMCURE", "ASTERDM", "HONASA"],
                "score": [9, 8, 7, 5, 4, 3],
                "return_1m_pct": [8.5, 7.1, 4.2, 3.8, -1.2, -2.1],
                "return_2m_pct": [12.4, 11.8, 7.6, 6.9, 2.1, 1.5],
                "return_3m_pct": [21.6, 19.3, 11.4, 13.3, 12.6, 9.5],
                "close": [5840, 8420, 796, 1590, 688, 307],
                "sl": [5600, 8060, 757, 1477, 637, 280],
                "target1": [6080, 8780, 838, 1703, 739, 335],
                "target2": [6320, 9140, 879, 1816, 790, 362],
                "delivery_pct": [72.4, 61.2, 55.1, 48.3, 42.1, 38.5],
                "cross_age": [4, 7, 12, 42, -1, 55],
                "fresh_cross": [True, True, False, False, False, False],
                "dist_pct": [3.2, 4.1, 5.8, 18.2, 8.1, 12.4],
                "overextended": [False, False, False, True, False, False],
                "acc_days": [4, 3, 3, 1, 2, 1],
                "dist_days": [0, 1, 1, 4, 2, 3],
                "obv_dir": ["rising", "rising", "flat", "falling", "flat", "falling"],
                "sector_bias": [1, 0, 1, 1, 0, 0],
                "streak": [3, 1, 6, 8, 2, 1],
                "category": ["uptrend", "rising", "rising", "peak", "safer", "recovering"],
            }
        )
        save_scan_results(df, date.today())
        print("✅ Test data saved\n")

    if args.demo:
        res = load_scan_results()
        if res:
            import re

            def strip(t):
                return re.sub(r"<[^>]+>", "", t)

            print(strip(format_welcome("Jayesh")))
            print("\n" + "=" * 50)
            print(strip(format_today_scan(res["stocks"], res["scan_date"])))
            print("\n" + "=" * 50)
            print(strip(format_prime_stocks(res["stocks"], res["scan_date"])))

    if args.history:
        h = load_history()
        print(f"History: {len(h)} days")
        print(f"New:    {[s['symbol'] for s in get_new_stocks(h)]}")
        print(f"Exit:   {[s['symbol'] for s in get_exit_stocks(h)]}")
        print(f"Strong: {[s['symbol'] for s in get_strong_stocks(h)]}")


if __name__ == "__main__":
    main()
