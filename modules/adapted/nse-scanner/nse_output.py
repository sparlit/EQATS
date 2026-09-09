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
nse_output.py — Report Generator (v8 — Full 25-stock morning message)
======================================================================
All 25 stocks get full detail cards in the morning Telegram message.
Grouped by situation: PRIME → HOLD → WATCH → BOOK → AVOID
Auto-splits into multiple messages to fit Telegram 4096 char limit.
"""

import contextlib
import glob
import json
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd
import requests

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    sys.exit(1)

try:
    from nse_telegram_handler import (
        PARSE_MODE,
        RESULTS_FILE,
        SITUATION_AVOID,
        SITUATION_BOOK,
        SITUATION_HOLD,
        SITUATION_META,
        SITUATION_ORDER,
        SITUATION_PRIME,
        SITUATION_WATCH,
        _compact_action_line,
        _plain_stock_card,
        save_scan_results,
    )

    _HANDLER_OK = True
    print(f"[OUTPUT] Pagination JSON: {RESULTS_FILE}")
except ImportError as e:
    save_scan_results = None
    RESULTS_FILE = None
    PARSE_MODE = "HTML"
    _HANDLER_OK = False
    SITUATION_META = {
        "prime": {"icon": "🎯", "label": "Prime Entry", "action": "Enter today"},
        "hold": {"icon": "💰", "label": "Hold & Trail", "action": "Trail your SL"},
        "watch": {"icon": "👀", "label": "Watch Closely", "action": "Monitor"},
        "book": {"icon": "⚠️", "label": "Book Profits", "action": "Protect gains"},
        "avoid": {"icon": "🚫", "label": "Avoid Now", "action": "Skip today"},
    }
    SITUATION_ORDER = ["prime", "hold", "watch", "book", "avoid"]
    SITUATION_PRIME = "prime"
    SITUATION_HOLD = "hold"
    SITUATION_WATCH = "watch"
    SITUATION_BOOK = "book"
    SITUATION_AVOID = "avoid"
    print(f"[WARN] nse_telegram_handler not found: {e}")

MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://jayeshsrathod.github.io/nse-scanner/")

# Chat IDs that receive the morning scan automatically
BROADCAST_CHAT_IDS = [
    "7872191203",  # Jayesh (admin)
    # "123456789",     # Add more users here
    # "-100xxxxxxxxx", # Group chat IDs (negative)
]

os.makedirs(config.LOG_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.FileHandler(os.path.join(config.LOG_DIR, "output.log")), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


# ── HTML helpers ──────────────────────────────────────────────


def _h(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _b(v):
    return f"<b>{_h(v)}</b>"


def _i(v):
    return f"<i>{_h(v)}</i>"


def _code(v):
    return f"<code>{_h(v)}</code>"


def _fmt_price(value):
    try:
        return f"₹{round(float(value)):,}"
    except (TypeError, ValueError):
        return "₹0"


SEP = "━" * 18
SEP2 = "─" * 18


# ── Telegram send ─────────────────────────────────────────────


def _send(text, keyboard=None, chat_id=None):
    target = chat_id or getattr(config, "TELEGRAM_CHATID", None)
    if not getattr(config, "TELEGRAM_TOKEN", None) or not target:
        log.warning("Telegram not configured")
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": str(target), "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            return True
        log.error(f"Telegram error {r.status_code}: {r.text[:300]}")
        data2 = {"chat_id": str(target), "text": text}
        if keyboard:
            data2["reply_markup"] = json.dumps(keyboard)
        return requests.post(url, data=data2, timeout=10).status_code == 200
    except Exception as e:
        log.exception(f"Telegram send failed: {e}")
        return False


# ── Keyboard ──────────────────────────────────────────────────


def build_morning_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Buy setups", "callback_data": "view_prime"},
                {"text": "📊 Today", "callback_data": "view_today"},
                {"text": "🆕 New", "callback_data": "view_new"},
                {"text": "📉 Exit", "callback_data": "view_exit"},
            ],
            [
                {"text": "⚠️ Caution", "callback_data": "view_caution"},
                {"text": "💰 Strong", "callback_data": "view_strong"},
                {"text": "📅 Digest", "callback_data": "/digest"},
                {"text": "📖 Guide", "callback_data": "guide"},
            ],
            [
                {"text": "📊 Open Scanner App", "web_app": {"url": MINI_APP_URL}},
            ],
        ]
    }


# ── Signal line helper ────────────────────────────────────────


def _signal_line(s):
    parts = []
    ca = int(s.get("cross_age", 999))
    dp = float(s.get("dist_pct", 0))
    acc = int(s.get("acc_days", 0))
    obv = str(s.get("obv_dir", "flat"))
    sb = int(s.get("sector_bias", 0))

    if ca == -1:
        parts.append("Bearish HMA")
    elif s.get("fresh_cross"):
        parts.append(f"🟢 Cross {ca}d")
    elif ca <= 20:
        parts.append(f"Cross {ca}d")
    elif ca < 999:
        parts.append(f"⚪ Cross {ca}d")

    if s.get("overextended"):
        parts.append(f"⚠️ {dp:.0f}% stretched")
    elif 0 < dp <= 5.0:
        parts.append(f"🟢 {dp:.1f}% room")
    elif dp > 0:
        parts.append(f"{dp:.1f}% above HMA")

    if acc >= 4 and obv == "rising":
        parts.append("🟢 Accum vol")
    elif obv == "falling":
        parts.append("🔴 Dist vol")

    if sb == 1:
        parts.append("Sector ✅")
    elif sb == -1:
        parts.append("Sector ❌")

    return " · ".join(parts)


# ── Full 25-stock message builder ─────────────────────────────


def format_option_c_messages(stocks_list, scan_date_str, greeting=""):
    """
    Build full 25-stock morning messages.
    Returns LIST of HTML strings (split by situation to fit 4096 limit).
    All stocks get full detail cards.
    """
    # The broadcast is organised by the next decision, not internal scores.
    # It is intentionally static: GitHub Actions cannot keep an interactive
    # Telegram session alive between daily workflow runs.
    try:
        ds = datetime.strptime(scan_date_str, "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        ds = scan_date_str

    groups = {
        key: []
        for key in ("BUY_TRIGGER", "WAIT_PULLBACK", "HOLD_TRAIL", "PARTIAL_PROFIT", "EXIT_ALERT", "WATCH", "AVOID")
    }
    for stock in stocks_list:
        groups.setdefault(stock.get("action", "WATCH"), []).append(stock)
    buy = groups["BUY_TRIGGER"]
    wait_only = groups["WAIT_PULLBACK"]
    watch_only = groups["WATCH"]
    wait = wait_only + watch_only
    manage = groups["HOLD_TRAIL"] + groups["PARTIAL_PROFIT"] + groups["EXIT_ALERT"]
    avoid = groups["AVOID"]

    def hull_badges(s):
        daily = "🟢 Daily Hull up" if s.get("daily_hull_status") == "BULLISH" else "🟡 Daily Hull not ready"
        weekly = "🟢 Weekly trend up" if s.get("weekly_hull_status") == "BULLISH" else "🟡 Weekly trend pending"
        return f"{daily} | {weekly}"

    def horizon_label(s):
        horizon = str(s.get("horizon", "NEW_1M_SETUP"))
        return {
            "NEW_1M_SETUP": "about 1 month",
            "DIRECT_3M": "1–3 months",
            "DIRECT_6M": "3–6 months",
            "CORE_12M": "6–12 months",
        }.get(horizon, "under observation")

    def return_trend(value):
        value = float(value or 0)
        return "🟢 Strong" if value >= 12 else "🟢 Positive" if value > 0 else "🟡 Building"

    def market_posture():
        if len(buy) >= 3:
            return "🟢 Positive, with multiple confirmed setups"
        if buy:
            return "🟢 Positive, but selective"
        if wait_only or watch_only:
            return "🟡 Selective — wait for confirmed entries"
        return "🔴 Defensive — no confirmed entry today"

    def why_wait(s):
        if s.get("hull_chop"):
            return "Price is moving sideways near the Hybrid Hull; direction is not clear yet."
        if s.get("hull_stretched"):
            distance = abs(float(s.get("hull_distance_atr", 0)))
            return f"Price is {distance:.1f} ATR above Hybrid Hull support; buying now would be chasing."
        if s.get("hull_compression"):
            return "Price is tightening into a possible breakout; wait for a close above the trigger with volume."
        if s.get("weekly_hull_status") != "BULLISH":
            return "Daily momentum is improving, but the weekly HMA21/51 trend is not fully confirmed."
        return str(s.get("action_reason") or "The trend is developing; wait for a complete EOD entry setup.")

    def buy_card(s, rank):
        close = float(s.get("close", 0))
        trigger = float(s.get("entry_trigger") or close)
        sl = float(s.get("sl", close * 0.93))
        t1 = float(s.get("target1", close))
        t2 = float(s.get("target2", close))
        reasons = [
            "Price is above the Hybrid Hull and not overstretched.",
            "Daily and weekly trend are aligned upward.",
        ]
        if int(s.get("acc_days", 0)) >= 3:
            reasons.append("Volume and delivery support the move.")
        else:
            reasons.append("Risk-to-reward remains acceptable at the trigger.")
        return (
            f"{_b(str(rank) + '. ' + str(s.get('symbol', '?')))} — {_b('BUY ONLY ABOVE ' + _fmt_price(trigger))}\n"
            f"   {_i('Setup strength: ' + str(round(float(s.get('score', 0)), 1)) + ' / 10')}\n"
            f"   {hull_badges(s)}\n"
            f"   3M trend: {return_trend(s.get('return_3m_pct'))} | 6M trend: {return_trend(s.get('return_6m_pct'))}\n"
            f"   Safety stop: {_b(_fmt_price(sl))}\n"
            f"   Profit plan: first {_fmt_price(t1)} | final {_fmt_price(t2)}\n"
            f"   Expected holding: {horizon_label(s)}\n"
            f"   Why actionable today:\n      • " + "\n      • ".join(reasons[:3]) + "\n"
            "   Entry window: next 2 trading sessions\n\n"
        )

    def wait_card(s, rank):
        close = float(s.get("close", 0))
        return (
            f"{_b(str(rank) + '. ' + str(s.get('symbol', '?')))} — close {_fmt_price(close)}\n"
            f"   {hull_badges(s)}\n"
            f"   Why wait: {why_wait(s)}\n"
            f"   Action today: {_b('Watch only; do not buy today.')}\n\n"
        )

    def manage_card(s):
        close = float(s.get("close", 0))
        protect = float(s.get("sl", close * 0.93))
        action = str(s.get("action", "HOLD_TRAIL"))
        instruction = (
            "Book some profit; protect the balance."
            if action == "PARTIAL_PROFIT"
            else "Exit or reduce the position."
            if action == "EXIT_ALERT"
            else "Hold only if already owned; raise the stop as price rises."
        )
        return (
            f"{_b(str(s.get('symbol', '?')))}: {instruction}\n"
            f"   Protect below {_b(_fmt_price(protect))} | {hull_badges(s)}\n\n"
        )

    def append_blocks(messages, initial, blocks, continuation):
        current = initial
        for block in blocks:
            if len(current) + len(block) > 3800:
                messages.append(current)
                current = continuation
            current += block
        return current

    header = greeting + f"📌 {_b('NSE TRADE PLAN — ' + ds)}\n"
    header += (
        f"{_i('Based on the previous market close. Fixed Hybrid Hull: 55 / HMA21 / HMA51 / ATR14 × 3.5 / KAMA30.')}\n\n"
    )
    header += f"{_b('MARKET POSTURE')}  {market_posture()}\n{SEP2}\n"
    header += (
        f"🎯 Act now: {_b(str(len(buy)))} | 👀 Wait: {_b(str(len(wait_only)))}\n"
        f"🧭 Watch: {_b(str(len(watch_only)))} | 🛡️ Manage: {_b(str(len(manage)))} | "
        f"🚫 Avoid: {_b(str(len(avoid)))}\n{SEP2}\n\n"
    )
    messages = []
    first = header + _b("✅ ACT TODAY — only after the trigger is crossed") + "\n"
    first += _i("Choose at most one or two. Do not buy before the stated price.") + "\n" + SEP2 + "\n\n"
    first = append_blocks(
        messages,
        first,
        [buy_card(s, i) for i, s in enumerate(buy, 1)],
        _b("✅ ACT TODAY — continued") + "\n" + SEP2 + "\n\n",
    )
    messages.append(first)

    second = _b("👀 GOOD STOCKS — WAIT, DO NOT CHASE") + "\n"
    second += (
        _i("These remain researched opportunities, but one clear condition is missing today.") + "\n" + SEP2 + "\n\n"
    )
    second = append_blocks(
        messages,
        second,
        [wait_card(s, i) for i, s in enumerate(wait, 1)],
        _b("👀 GOOD STOCKS — continued") + "\n" + SEP2 + "\n\n",
    )
    if manage:
        second += SEP2 + "\n" + _b("🛡️ IF YOU ALREADY OWN THESE") + "\n" + SEP2 + "\n\n"
        second = append_blocks(
            messages,
            second,
            [manage_card(s) for s in manage],
            _b("🛡️ POSITION MANAGEMENT — continued") + "\n" + SEP2 + "\n\n",
        )
    if avoid:
        second += SEP2 + "\n" + _b("🚫 AVOID TODAY") + "\n   "
        second += ", ".join(_code(str(s.get("symbol", "?"))) for s in avoid) + "\n"
    second += f"\n{SEP}\nSimple rule: buy only after the trigger; always respect the safety stop."
    messages.append(second)
    return [message for message in messages if message.strip()]

    try:
        ds = datetime.strptime(scan_date_str, "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        ds = scan_date_str

    total = len(stocks_list)
    avg_score = sum(float(s.get("score", 0)) for s in stocks_list) / max(total, 1)

    # Count per situation
    sit_counts = {}
    for s in stocks_list:
        sit = s.get("situation", "watch")
        sit_counts[sit] = sit_counts.get(sit, 0) + 1

    # ── Message 1: Header ──
    header = greeting
    header += f"📊 {_b('NSE Scan — ' + ds)}\n"
    header += f"{_i(str(total) + ' stocks · Avg score ' + str(round(avg_score, 1)))}\n"

    parts = []
    for sit in SITUATION_ORDER:
        if sit in sit_counts:
            sm = SITUATION_META.get(sit, {})
            parts.append(f"{sm.get('icon', '·')} {sit_counts[sit]} {sm.get('label', sit).split()[0].lower()}")
    header += " | ".join(parts) + "\n"

    messages = [header]

    # ── One message per situation group — full detail cards ──
    rank = 1
    for sit in SITUATION_ORDER:
        group = [s for s in stocks_list if s.get("situation") == sit]
        if not group:
            continue

        sm = SITUATION_META.get(sit, {})
        msg = f"\n{SEP2}\n"
        msg += (
            f"{sm.get('icon', '')} {_b(sm.get('label', sit) + ' (' + str(len(group)) + ')')} — {sm.get('action', '')}\n"
        )
        msg += f"{SEP2}\n\n"

        for s in group:
            e = float(s.get("close", 0))
            sl = float(s.get("sl", e * 0.93))
            t1 = float(s.get("target1", e + (e - sl)))
            t2 = float(s.get("target2", e + 2 * (e - sl)))
            sc = round(float(s.get("score", 0)))
            r3 = float(s.get("return_3m_pct", 0))
            r1 = float(s.get("return_1m_pct", 0))
            st = int(s.get("streak", 0))

            t1p = (t1 - e) / e * 100 if e > 0 else 0
            t2p = (t2 - e) / e * 100 if e > 0 else 0

            stag = f" 🔥{st}d" if st >= 5 else ""
            ca_tag = " 🟢Fresh" if s.get("fresh_cross") else ""

            block = f"{_b(str(rank) + '. ' + s['symbol'])}  {sc}/10{stag}{ca_tag}\n"
            block += f"   Entry ₹{int(e):,} | SL ₹{int(sl):,}\n"
            block += f"   T1 ₹{int(t1):,} (+{t1p:.1f}%) · T2 ₹{int(t2):,} (+{t2p:.1f}%)\n"

            sig = _signal_line(s)
            if sig:
                block += f"   {_i(sig)}\n"

            block += f"   1M {r1:+.1f}% | 3M {r3:+.1f}%\n\n"

            # Split if message too long
            if len(msg) + len(block) > 3800:
                messages.append(msg)
                msg = f"{sm.get('icon', '')} {_b(sm.get('label', sit) + ' (contd.)')}\n{SEP2}\n\n"

            msg += block
            rank += 1

        messages.append(msg)

    # Footer on last message
    footer = f"\n{SEP}\n"
    footer += f"Total: {total} stocks | 🎯 Prime: {sit_counts.get(SITUATION_PRIME, 0)}\n"
    footer += _i("Tap Prime for entry details · TV confirms timing")
    messages[-1] += footer

    return messages


# ── Welcome scan (for /start and Hi/Hello) ────────────────────


def format_welcome_scan(user_name=""):
    greeting = f"👋 {_b('Hello ' + _h(user_name) + '!')}\n\n" if user_name else f"👋 {_b('Hello!')}\n\n"

    if RESULTS_FILE and os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            stocks = data.get("stocks", [])
            scan_date = data.get("scan_date", "")
            if stocks:
                msgs = format_option_c_messages(stocks, scan_date, greeting)
                combined = "\n".join(msgs)
                if len(combined) > 4000:
                    combined = combined[:3950] + f"\n\n{_i('... tap Today for full list')}"
                return combined, build_morning_keyboard()
        except Exception as e:
            log.warning(f"format_welcome_scan error: {e}")

    msg = greeting
    msg += f"📊 {_b('NSE Scanner Daily')}\n\n"
    msg += f"{_i('Scan data not available yet.')}\n"
    msg += "Pipeline runs at 6:00 AM IST daily.\n"
    return msg, build_morning_keyboard()


# ── Pagination JSON + Tracker ─────────────────────────────────


def _save_pagination_json(results_df, report_date):
    if not _HANDLER_OK or save_scan_results is None:
        log.error("[BOT] Cannot save pagination JSON — handler not loaded")
        return
    df = results_df.copy()
    sit_pri = {SITUATION_PRIME: 0, SITUATION_HOLD: 1, SITUATION_WATCH: 2, SITUATION_BOOK: 3, SITUATION_AVOID: 4}
    if "situation" in df.columns:
        df["_sp"] = df["situation"].map(lambda s: sit_pri.get(s, 2))
        df = df.sort_values(["_sp", "score"], ascending=[True, False]).drop(columns=["_sp"])
    elif "score" in df.columns:
        df = df.sort_values("score", ascending=False)
    df = df.reset_index(drop=True)

    try:
        save_scan_results(df, report_date)
        log.info(f"[BOT] Pagination JSON saved -> {RESULTS_FILE}")
        if RESULTS_FILE and os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, encoding="utf-8") as f:
                check = json.load(f)
            log.info(f"[BOT] JSON: {check['total_stocks']} stocks, date={check['scan_date']}")
            try:
                from nse_signal_tracker import update_tracker
                from nse_telegram_handler import load_history as _lh

                summary = update_tracker(check["stocks"], check["scan_date"], _lh())
                log.info(f"[TRACKER] {summary}")
            except Exception as te:
                log.warning(f"[TRACKER] Skipped: {te}")
    except Exception as e:
        log.error(f"[BOT] save_scan_results FAILED: {e}", exc_info=True)


# ── Send Telegram — morning message to all broadcast users ───


def send_telegram(results_df, report_date):
    if not getattr(config, "TELEGRAM_TOKEN", None):
        log.warning("Telegram not configured")
        return False
    if results_df.empty:
        log.warning("Empty DataFrame")
        return False

    # Step 1: Save JSON
    _save_pagination_json(results_df, report_date)

    # Step 2: Build messages from saved JSON
    try:
        if RESULTS_FILE and os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            stocks_list = data.get("stocks", [])
            scan_date = data.get("scan_date", str(report_date))
        else:
            stocks_list = _df_to_list(results_df)
            scan_date = str(report_date)
        messages = format_option_c_messages(stocks_list, scan_date)
    except Exception as e:
        log.error(f"Message build failed: {e}", exc_info=True)
        messages = [_fmt_fallback(results_df, report_date)]

    # Step 3: Build recipient list
    recipients = set(BROADCAST_CHAT_IDS)
    admin_id = getattr(config, "TELEGRAM_CHATID", None)
    if admin_id:
        recipients.add(str(admin_id))

    # Step 4: Send to all recipients
    total_sent = 0

    for chat_id in recipients:
        try:
            for i, msg in enumerate(messages):
                (i == len(messages) - 1)
                _send(msg, chat_id=chat_id)
            total_sent += 1
            log.info(f"Morning scan sent to {chat_id}")
        except Exception as e:
            log.exception(f"Failed to send to {chat_id}: {e}")

    log.info(f"Broadcast: {total_sent} sent, {len(messages)} msgs, {len(stocks_list)} stocks")

    # Step 5: Admin confirmation
    if total_sent > 0:
        try:
            from nse_bot_admin import send_pipeline_confirmation

            prime_n = sum(1 for s in stocks_list if s.get("situation") == SITUATION_PRIME)
            send_pipeline_confirmation(
                scan_date=report_date.strftime("%d-%b-%Y"),
                stock_count=len(stocks_list),
                prime_count=int(prime_n),
                run_time=datetime.now().strftime("%I:%M %p IST"),
            )
        except Exception as _pe:
            log.warning(f"Pipeline confirmation skipped: {_pe}")

    return total_sent > 0


def _df_to_list(df):
    rows = []
    for _, row in df.iterrows():
        e = float(row.get("close", 0))
        sl = float(row.get("sl", e * 0.93))
        rows.append(
            {
                "symbol": str(row["symbol"]),
                "score": round(float(row.get("score", 0)), 1),
                "situation": str(row.get("situation", "watch")),
                "close": round(e, 2),
                "sl": round(sl, 2),
                "target1": round(float(row.get("target1", e + (e - sl))), 2),
                "target2": round(float(row.get("target2", e + 2 * (e - sl))), 2),
                "return_1m_pct": round(float(row.get("return_1m_pct", 0)), 1),
                "return_3m_pct": round(float(row.get("return_3m_pct", 0)), 1),
                "return_6m_pct": round(float(row.get("return_6m_pct", 0)), 1),
                "return_12m_pct": round(float(row.get("return_12m_pct", 0)), 1),
                "streak": int(row.get("streak", 0)),
                "cross_age": int(row.get("cross_age", 999)),
                "fresh_cross": bool(row.get("fresh_cross", False)),
                "dist_pct": round(float(row.get("dist_pct", 0)), 1),
                "overextended": bool(row.get("overextended", False)),
                "acc_days": int(row.get("acc_days", 0)),
                "dist_days": int(row.get("dist_days", 0)),
                "obv_dir": str(row.get("obv_dir", "flat")),
                "sector_bias": int(row.get("sector_bias", 0)),
                "weekly_label": str(row.get("weekly_label", "")),
                "daily_hull_status": str(row.get("daily_hull_status", "NOT_ALIGNED")),
                "daily_hma_aligned": bool(row.get("daily_hma_aligned", False)),
                "kama_rising": bool(row.get("kama_rising", False)),
                "weekly_hull_status": str(row.get("weekly_hull_status", "NOT_ALIGNED")),
                "hull_distance_atr": round(float(row.get("hull_distance_atr", 0)), 2),
                "hull_stretched": bool(row.get("hull_stretched", False)),
                "hull_chop": bool(row.get("hull_chop", False)),
                "hull_compression": bool(row.get("hull_compression", False)),
            }
        )
    return rows


def _fmt_fallback(df, report_date):
    try:
        ds = report_date.strftime("%d-%b-%Y")
    except Exception:
        ds = str(report_date)
    msg = f"📊 {_b('NSE Scan — ' + ds)}\n\n"
    for i, (_, row) in enumerate(df.head(6).iterrows(), 1):
        e = float(row.get("entry", row.get("close", 0)))
        sc = int(row.get("score", 0))
        sit = str(row.get("situation", "watch"))
        msg += (
            f"{i}. {_code(str(row['symbol']))}  {sc}/10  "
            f"{SITUATION_META.get(sit, {}).get('icon', '')}\n"
            f"   Rs {int(e):,}\n\n"
        )
    msg += _i("Send /prime for entry-ready stocks")
    return msg


# ── Excel ─────────────────────────────────────────────────────


def save_excel(results_df, report_date):
    if results_df.empty:
        return None
    for f in glob.glob(os.path.join(config.OUTPUT_DIR, "NSE_Scanner_*.xlsx")):
        with contextlib.suppress(Exception):
            os.remove(f)

    df = results_df.copy()
    sit_pri = {SITUATION_PRIME: 0, SITUATION_HOLD: 1, SITUATION_WATCH: 2, SITUATION_BOOK: 3, SITUATION_AVOID: 4}
    if "situation" in df.columns:
        df["_sp"] = df["situation"].map(lambda s: sit_pri.get(s, 2))
        df = df.sort_values(["_sp", "score"], ascending=[True, False]).drop(columns=["_sp"])
    elif "score" in df.columns:
        df = df.sort_values("score", ascending=False)
    df = df.reset_index(drop=True)

    rename = {
        "symbol": "Symbol",
        "situation": "Situation",
        "score": "FwdScore",
        "return_1m_pct": "1M%",
        "return_2m_pct": "2M%",
        "return_3m_pct": "3M%(ref)",
        "close": "Close",
        "avg_volume": "AvgVolume",
        "delivery_pct": "DelivPct",
        "entry": "Entry",
        "sl": "StopLoss",
        "sl_pct": "SL%",
        "target1": "Target1",
        "t1_pct": "T1%",
        "target2": "Target2",
        "t2_pct": "T2%",
        "rr": "RR",
        "category": "Category",
        "streak": "Streak",
        "cross_age": "HMA_CrossAge",
        "dist_pct": "Dist_HMA55%",
        "fresh_cross": "FreshCross",
        "overextended": "Overextended",
        "acc_days": "AccumDays",
        "dist_days": "DistribDays",
        "obv_dir": "OBV_Dir",
        "sector_bias": "SectorBias",
        "weekly_tier": "WeeklyTier",
        "weekly_label": "WeeklyLabel",
        "conviction": "Conviction",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df.insert(0, "Rank", range(1, len(df) + 1))

    order = [
        "Rank",
        "Symbol",
        "Situation",
        "FwdScore",
        "Streak",
        "WeeklyTier",
        "WeeklyLabel",
        "HMA_CrossAge",
        "Dist_HMA55%",
        "FreshCross",
        "Overextended",
        "AccumDays",
        "DistribDays",
        "OBV_Dir",
        "SectorBias",
        "Entry",
        "StopLoss",
        "SL%",
        "Target1",
        "T1%",
        "Target2",
        "T2%",
        "RR",
        "1M%",
        "2M%",
        "3M%(ref)",
        "Close",
        "AvgVolume",
        "DelivPct",
        "Conviction",
        "Category",
    ]
    df = df[[c for c in order if c in df.columns]]

    fname = f"NSE_Scanner_{report_date.strftime('%Y-%m-%d')}.xlsx"
    fpath = os.path.join(config.OUTPUT_DIR, fname)
    try:
        df.to_excel(fpath, sheet_name="NSE_Scanner", index=False)
        log.info(f"Excel saved: {fpath}")
        return fpath
    except Exception as e:
        log.exception(f"Excel save failed: {e}")
        return None


# ── Generate Report ───────────────────────────────────────────


def generate_report(results_df, report_date=None):
    if report_date is None:
        report_date = date.today()

    print(f"\n{'=' * 56}\n  NSE OUTPUT v8\n{'=' * 56}")

    results = {
        "excel_file": None,
        "telegram_sent": False,
        "date": report_date,
        "stocks_count": len(results_df),
    }

    excel_file = save_excel(results_df, report_date)
    if excel_file:
        results["excel_file"] = excel_file
        print(f"Excel: {os.path.basename(excel_file)}")

    ok = send_telegram(results_df, report_date)
    results["telegram_sent"] = ok
    prime = (results_df["situation"] == SITUATION_PRIME).sum() if "situation" in results_df.columns else 0
    print(f"Telegram: {'sent' if ok else 'failed'}")
    print(f"Stocks: {len(results_df)} | Prime: {prime}")

    if RESULTS_FILE and os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, encoding="utf-8") as f:
                check = json.load(f)
            expected = report_date.strftime("%Y-%m-%d")
            if check.get("scan_date") != expected:
                log.warning(f"JSON date mismatch: {expected} vs {check.get('scan_date')}")
        except Exception as e:
            log.warning(f"JSON check failed: {e}")

    return results


# ── CLI ───────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    report_date = date.today()
    if args.date:
        report_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    if args.preview:
        msg, _ = format_welcome_scan("Jayesh")
        import re

        print(re.sub(r"<[^>]+>", "", msg))
        return

    if args.test:
        df = pd.DataFrame(
            {
                "symbol": ["KAYNES", "DIXON", "SYRMA", "ASTERDM", "EMCURE", "HONASA"],
                "score": [9, 8, 7, 6, 5, 3],
                "situation": ["prime", "prime", "hold", "watch", "book", "avoid"],
                "conviction": ["HIGH CONVICTION"] * 3 + ["Watchlist"] * 2 + [""],
                "return_1m_pct": [8.5, 7.1, 4.2, 3.1, 2.1, -2.1],
                "return_2m_pct": [12.4, 11.8, 7.6, 5.8, 4.3, 1.5],
                "return_3m_pct": [21.6, 19.3, 11.4, 12.6, 13.3, 9.5],
                "close": [5840, 8420, 796, 688, 1590, 307],
                "entry": [5840, 8420, 796, 688, 1590, 307],
                "sl": [5600, 8060, 757, 655, 1477, 280],
                "sl_pct": [-4.1, -4.3, -4.9, -4.8, -7.1, -8.8],
                "target1": [6080, 8780, 835, 721, 1703, 334],
                "t1_pct": [4.1, 4.3, 4.9, 4.8, 7.1, 8.8],
                "target2": [6320, 9140, 874, 754, 1816, 361],
                "t2_pct": [8.2, 8.5, 9.8, 9.6, 14.2, 17.6],
                "rr": [2.0] * 6,
                "avg_volume": [87210, 125430, 234100, 180000, 95000, 420000],
                "delivery_pct": [72.4, 61.2, 55.1, 58.3, 48.3, 38.5],
                "cross_age": [4, 7, 12, 18, 42, -1],
                "fresh_cross": [True, True, False, False, False, False],
                "dist_pct": [3.2, 4.1, 5.8, 6.2, 18.2, 0],
                "overextended": [False, False, False, False, True, False],
                "acc_days": [4, 3, 3, 2, 1, 1],
                "dist_days": [0, 1, 1, 1, 4, 3],
                "obv_dir": ["rising", "rising", "flat", "rising", "falling", "falling"],
                "sector_bias": [1, 0, 1, 1, 1, 0],
                "weekly_tier": [1, 1, 2, 2, 1, 3],
                "weekly_label": ["Weekly Bullish"] * 2 + ["Weekly Pullback"] * 2 + ["Weekly Bullish", "Weekly Bearish"],
                "category": ["uptrend", "uptrend", "rising", "safer", "peak", "recovering"],
                "streak": [3, 1, 6, 2, 8, 1],
                "momentum_score": [0.18, 0.16, 0.10, 0.09, 0.12, 0.08],
            }
        )
    else:
        from nse_scanner import scan_stocks

        df = scan_stocks(scan_date=report_date)
        if df.empty:
            print("No scanner results")
            return

    generate_report(df, report_date)


if __name__ == "__main__":
    main()
