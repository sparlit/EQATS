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
nse_smart_buckets.py — Smart Bucket Classification (v2 — Situation Aligned)
=============================================================================
WHAT CHANGED FROM v1:
  OLD: Classified stocks into 6 buckets (rising/uptrend/peak/recovery/safe/caution)
       Based purely on technical category labels
  NEW: Aligned with situation engine (prime/hold/watch/book/avoid)
       Buckets now map to situations + add visual grouping within each situation

PURPOSE:
  Provides the /buckets view in the Telegram bot.
  Shows stocks grouped visually within each situation with
  extra context (streak, weekly tier, return, probability).

EXPORTS (same interface as v1 for polling.py compatibility):
  classify_current_scan()       → (classified_dict, scan_date)
  format_bucketed_message()     → HTML message for /buckets view
  format_bucket_detail()        → HTML for tapping into a bucket
  BUCKET_RISING, BUCKET_UPTREND, BUCKET_PEAK,
  BUCKET_RECOVERY, BUCKET_SAFE, BUCKET_CAUTION
  (kept as aliases so polling.py BUCKET_CB dict still works)
"""

import json
import os
from datetime import datetime

# ── Bucket constants (aliases to situations for backward compat) ──
BUCKET_PRIME = "prime"
BUCKET_HOLD = "hold"
BUCKET_WATCH = "watch"
BUCKET_BOOK = "book"
BUCKET_AVOID = "avoid"

# Legacy aliases — polling.py uses these in BUCKET_CB dict
BUCKET_RISING = "prime"  # was: consistently rising → now: prime entry
BUCKET_UPTREND = "hold"  # was: clear uptrend → now: hold & trail
BUCKET_PEAK = "watch"  # was: close to peak → now: watch closely
BUCKET_RECOVERY = "watch"  # was: recovering → now: watch closely
BUCKET_SAFE = "watch"  # was: safer bets → now: watch closely
BUCKET_CAUTION = "avoid"  # was: caution → now: avoid / book

# Display metadata per bucket/situation
BUCKET_META = {
    "prime": {
        "icon": "🎯",
        "label": "Prime Entry",
        "desc": "Best forward probability today. Fresh cross, room to run, volume confirming.",
        "action": "Confirm on TradingView → Enter",
        "color": "green",
    },
    "hold": {
        "icon": "💰",
        "label": "Hold & Trail",
        "desc": "In sustained move for 5+ days. Trail your stop loss up.",
        "action": "Move SL up → Let it run",
        "color": "teal",
    },
    "watch": {
        "icon": "👀",
        "label": "Watch Closely",
        "desc": "Good setup, one signal missing. Could be prime in 1-3 days.",
        "action": "Monitor daily → Enter when ready",
        "color": "blue",
    },
    "book": {
        "icon": "⚠️",
        "label": "Book Profits",
        "desc": "Move is maturing. Stretched or cross is 30+ days old.",
        "action": "Book 50-100% → Protect gains",
        "color": "orange",
    },
    "avoid": {
        "icon": "🚫",
        "label": "Avoid Now",
        "desc": "Weak signal, distribution, or weekly trend broken.",
        "action": "Skip today → Better setups tomorrow",
        "color": "red",
    },
}

BUCKET_ORDER = ["prime", "hold", "watch", "book", "avoid"]

_HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(_HERE, "telegram_last_scan.json")


# ── HTML helpers ──────────────────────────────────────────────


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


def _date_str(scan_date):
    try:
        return datetime.strptime(scan_date or "", "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        return scan_date or "Today"


# ═══════════════════════════════════════════════════════════════
# CLASSIFY CURRENT SCAN
# ═══════════════════════════════════════════════════════════════


def classify_current_scan():
    """
    Load current scan and classify stocks by situation.

    Returns:
        (classified_dict, scan_date_str)
        classified_dict = {"prime": [...], "hold": [...], ...}
        None, None on error
    """
    if not os.path.exists(RESULTS_FILE):
        return None, None

    try:
        with open(RESULTS_FILE, encoding="utf-8") as f:
            data = json.load(f)

        stocks = data.get("stocks", [])
        scan_date = data.get("scan_date", "")

        if not stocks:
            return None, None

        classified = {sit: [] for sit in BUCKET_ORDER}

        for stock in stocks:
            sit = stock.get("situation", "watch")
            # Ensure it's a valid situation key
            if sit not in classified:
                sit = "watch"
            classified[sit].append(stock)

        return classified, scan_date

    except Exception as e:
        print(f"[BUCKETS] classify error: {e}")
        return None, None


# ═══════════════════════════════════════════════════════════════
# FORMAT BUCKETED MESSAGE — /buckets overview
# ═══════════════════════════════════════════════════════════════


def format_bucketed_message(classified, scan_date=None):
    """
    Format the /buckets overview message.
    Shows all situations with compact stock lists and counts.
    """
    ds = _date_str(scan_date)
    sum(len(v) for v in classified.values())

    msg = f"🗂️ {_b('Situation Buckets — ' + ds)}\n"
    msg += f"{_i('Stocks grouped by forward signal quality')}\n"
    msg += "─" * 34 + "\n\n"

    for sit in BUCKET_ORDER:
        stocks = classified.get(sit, [])
        if not stocks:
            continue

        bm = BUCKET_META.get(sit, {})
        msg += f"{bm.get('icon', '')} {_b(bm.get('label', sit.title()))} ({len(stocks)})\n"
        msg += f"   {_i(bm.get('desc', ''))}\n"

        # Compact list — symbol + score
        symbols_str = ", ".join(f"{_code(s['symbol'])} {round(float(s.get('score', 0)))}/10" for s in stocks[:6])
        msg += f"   {symbols_str}"
        if len(stocks) > 6:
            msg += f" +{len(stocks) - 6} more"
        msg += "\n\n"

    # Prime call to action
    prime_count = len(classified.get("prime", []))
    if prime_count > 0:
        msg += "─" * 34 + "\n"
        msg += f"🎯 {_b(str(prime_count) + ' stock(s) ready to enter today')}\n"
        msg += f"{_i('Tap Prime for full details + TV checklist')}\n"
    else:
        msg += "─" * 34 + "\n"
        msg += f"{_i('No prime entries today — market consolidating')}\n"

    return msg


# ═══════════════════════════════════════════════════════════════
# FORMAT BUCKET DETAIL — Tapping into one bucket
# ═══════════════════════════════════════════════════════════════


def format_bucket_detail(situation, classified, scan_date=None):
    """
    Format detailed view for one bucket/situation.
    Called when user taps a bucket button.
    """
    ds = _date_str(scan_date)
    stocks = classified.get(situation, [])
    bm = BUCKET_META.get(situation, {})

    if not stocks:
        return (
            f"{bm.get('icon', '')} {_b(bm.get('label', situation.title()))}\n\n{_i('No stocks in this bucket today.')}"
        )

    msg = f"{bm.get('icon', '')} {_b(bm.get('label', situation.title()) + ' — ' + ds)}\n"
    msg += f"{_i(bm.get('desc', ''))}\n"
    msg += f"{_i('Action: ' + bm.get('action', ''))}\n"
    msg += "─" * 34 + "\n\n"

    for i, s in enumerate(stocks, 1):
        sc = round(float(s.get("score", 0)))
        e = float(s.get("close", 0))
        sl = float(s.get("sl", e * 0.93))
        t1 = float(s.get("target1", e + (e - sl)))
        t2 = float(s.get("target2", e + 2 * (e - sl)))
        r3 = float(s.get("return_3m_pct", 0))
        streak = int(s.get("streak", 0))
        ca = int(s.get("cross_age", 999))
        dp = float(s.get("dist_pct", 0))
        w_label = s.get("weekly_label", "")

        streak_str = f" 🔥{streak}d" if streak >= 5 else ""
        ca_str = f"Cross {ca}d" if 0 < ca < 999 else ""

        msg += f"{_b(str(i) + '.')} {_code(s['symbol'])}  {sc}/10{streak_str}\n"
        msg += f"   Entry {_fmt_price(e)} | SL {_fmt_price(sl)}\n"
        msg += f"   T1 {_fmt_price(t1)} | T2 {_fmt_price(t2)}\n"
        msg += f"   3M {_fmt_return(r3)}"

        if ca_str:
            msg += f" | {_i(ca_str)}"
        if dp > 0:
            msg += f" | {dp:.1f}% room"
        if w_label:
            msg += f"\n   {_i(w_label)}"
        msg += "\n\n"

    msg += "─" * 34 + "\n"
    msg += f"{len(stocks)} stock(s) in this bucket"
    return msg


# ═══════════════════════════════════════════════════════════════
# LEGACY FORMAT FUNCTIONS (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════


def format_category_message(classified, scan_date=None):
    """Alias for format_bucketed_message — backward compat."""
    return format_bucketed_message(classified, scan_date)


def get_stocks_in_bucket(situation, classified):
    """Get list of stocks in a situation bucket."""
    return classified.get(situation, [])


def get_bucket_summary(classified):
    """Returns compact summary dict for admin/health reports."""
    return {sit: len(stocks) for sit, stocks in classified.items()}
