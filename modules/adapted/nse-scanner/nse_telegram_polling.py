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
nse_telegram_polling.py — Telegram Polling Bot (Phase 2.3 — Situation Engine)
==============================================================================
v2.3.1: Portfolio commands added
  - /portfolio — open positions + live P/L
  - /exits     — closed trade history
  - /returns   — win rate + performance stats
  - 💼 Portfolio button in keyboard Row 2
  - NLP: "portfolio", "holdings", "pnl", "returns" etc.

─────────────────────────────────────────────────────────────────
CREDENTIALS — WHERE TO PUT THEM
─────────────────────────────────────────────────────────────────
This local bot reads credentials from config.py in the same folder.

In your LOCAL config.py add/update these two lines:

    TELEGRAM_TOKEN  = "YOUR_NSE_SCANNER_BOT_TOKEN_HERE"
    TELEGRAM_CHATID = "YOUR_CHAT_ID_HERE"

The nse_scanner_bot token is DIFFERENT from nse_scanner_live token.
Each bot has its own token from @BotFather.
Both bots can send to the same TELEGRAM_CHATID (your personal chat).

If you use a .env file instead, add:
    TELEGRAM_TOKEN=YOUR_NSE_SCANNER_BOT_TOKEN_HERE
    TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
─────────────────────────────────────────────────────────────────
"""

import contextlib
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta

try:
    import requests
except ImportError:
    print("ERROR: requests not installed")
    sys.exit(1)

try:
    import config
except ImportError:
    print("ERROR: config.py not found")
    sys.exit(1)

# ── Handler imports ───────────────────────────────────────────
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
        _b,
        _code,
        _fmt_return,
        _h,
        assign_situation,
        format_caution_stocks,
        format_exit_stocks,
        format_exits,
        format_help,
        format_new_stocks,
        # Portfolio commands (v6.1)
        format_portfolio,
        format_prime_stocks,
        format_returns,
        format_stock_list,
        format_strong_stocks,
        format_summary,
        format_today_scan,
        format_welcome,
        get_exit_stocks,
        get_new_stocks,
        get_strong_stocks,
        load_history,
        load_scan_results,
        sort_stocks,
    )

    print("[POLL] Handler imports OK")
except ImportError as e:
    print(f"ERROR importing handler: {e}")
    sys.exit(1)

# ── Optional modules ──────────────────────────────────────────
_ADMIN_OK = False
_TRACKER_OK = False
_DIGEST_OK = False

try:
    from nse_bot_admin import (
        format_guide_message,
        format_health_report,
        format_user_list,
        generate_health_report,
        get_user_count,
        is_admin,
        is_blocked,
        log_activity,
        send_health_check,
        track_user,
    )

    _ADMIN_OK = True
    print("[POLL] Admin loaded")
except ImportError:

    def track_user(u):
        pass

    def log_activity(uid, t, d):
        pass

    def is_admin(uid):
        return False

    def is_blocked(uid):
        return False

    def get_user_count():
        return 0


try:
    from nse_signal_tracker import (
        calculate_probability,
        format_signal_card,
        get_signal,
        get_tracker_summary,
    )

    _TRACKER_OK = True
    print("[POLL] Tracker loaded")
except ImportError:

    def get_signal(s):
        return None

    def get_tracker_summary():
        return {}


try:
    from nse_weekly_digest import (
        analyze_week,
        format_weekly_digest,
        get_week_dates,
        get_week_history,
        get_week_prices,
    )

    _DIGEST_OK = True
    print("[POLL] Digest loaded")
except ImportError:
    print("[WARN] nse_weekly_digest not found")

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("logs/polling_bot.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── nse_output helpers ────────────────────────────────────────
_OUTPUT_OK = False
try:
    from nse_output import build_morning_keyboard, format_welcome_scan

    _OUTPUT_OK = True
    print("[POLL] nse_output loaded (Option C welcome)")
except ImportError as _oe:
    print(f"[WARN] nse_output not loaded: {_oe}")

    def format_welcome_scan(name=""):
        return ("No data yet.", {})

    def build_morning_keyboard():
        return {"inline_keyboard": []}


GUIDE_PDF_URL = os.environ.get(
    "GUIDE_PDF_URL",
    "https://htmlpreview.github.io/?https://github.com/JayeshSRathod/nse-scanner/blob/main/docs/NSE_Scanner_Guide.html",
)


# ═══════════════════════════════════════════════════════════════
# FAKE USER
# ═══════════════════════════════════════════════════════════════


class FakeUser:
    def __init__(self, d):
        d = d or {}
        self.id = d.get("id", 0)
        self.username = d.get("username", "")
        self.first_name = d.get("first_name", "")
        self.last_name = d.get("last_name", "")


# ═══════════════════════════════════════════════════════════════
# NLP — Text → Command resolver
# ═══════════════════════════════════════════════════════════════

GREETINGS = {
    "hi",
    "hii",
    "hiii",
    "hello",
    "hey",
    "helo",
    "hlo",
    "start",
    "begin",
    "go",
    "good morning",
    "good evening",
    "good afternoon",
    "gm",
    "ge",
    "ga",
    "namaste",
    "namaskar",
    "jai hind",
}
NEXT_WORDS = {"next", "n", "aage", "more", "forward"}
PREV_WORDS = {"prev", "previous", "p", "back", "peeche"}
NEWS_WORDS = {"news", "headline", "headlines", "khabar"}
TOP_WORDS = {"top", "best", "top10", "winners", "leader"}
LIST_WORDS = {"list", "all", "summary", "sab"}
HELP_WORDS = {"help", "?", "commands", "menu"}
NEW_WORDS = {"new", "new entry", "fresh", "naya"}
EXIT_WORDS = {"exit", "exited", "left", "bahar"}
STRONG_WORDS = {"strong", "streak", "consistent", "hold", "trail", "hold trail"}
CAUTION_WORDS = {"caution", "risk", "warning", "careful", "avoid"}
TODAY_WORDS = {"today", "scan", "aaj"}
GUIDE_WORDS = {"guide", "pdf", "how", "learn", "tutorial", "padho", "sikho"}
ADMIN_WORDS = {"admin", "dashboard", "panel"}
DIGEST_WORDS = {"digest", "weekly", "week", "performance", "hafta"}
PRIME_WORDS = {
    "prime",
    "enter today",
    "enter",
    "best pick",
    "top pick",
    "ready",
    "entry ready",
    "buy today",
    "prime entry",
}
# Portfolio NLP words
PORTFOLIO_WORDS = {"portfolio", "positions", "holdings", "my stocks", "open positions"}
EXITS_WORDS = {"exits", "closed", "exited trades", "closed trades", "trade history"}
RETURNS_WORDS = {"returns", "pnl", "p&l", "profit loss", "performance", "win rate"}


def resolve_text_to_command(text):
    c = text.strip().lower()
    if c.startswith("/"):
        return c
    if c in (
        "next",
        "prev",
        "list",
        "help",
        "news",
        "sort_score",
        "sort_3m",
        "sort_top10",
        "noop",
        "view_today",
        "view_new",
        "view_exit",
        "view_caution",
        "view_strong",
        "view_prime",
        "view_portfolio",
        "summary",
        "back_from_card",
        "back_to_main",
        "main_menu",
        "guide",
        "broadcast_confirm",
    ) or c.startswith(("page_", "stock_")):
        return c
    if c in GREETINGS:
        return "/start"
    if c.isdigit() and 1 <= int(c) <= 99:
        return f"/page {c}"
    if c.startswith("page ") and c[5:].isdigit():
        return f"/page {c[5:]}"
    if c in NEXT_WORDS:
        return "/next"
    if c in PREV_WORDS:
        return "/prev"
    if c in NEWS_WORDS:
        return "/news"
    if c in TOP_WORDS:
        return "sort_top10"
    if c in LIST_WORDS:
        return "summary"
    if c in HELP_WORDS:
        return "/help"
    if c in NEW_WORDS:
        return "view_new"
    if c in EXIT_WORDS:
        return "view_exit"
    if c in STRONG_WORDS:
        return "view_strong"
    if c in CAUTION_WORDS:
        return "view_caution"
    if c in TODAY_WORDS:
        return "view_today"
    if c in PRIME_WORDS:
        return "view_prime"
    if c in PORTFOLIO_WORDS:
        return "/portfolio"
    if c in EXITS_WORDS:
        return "/exits"
    if c in RETURNS_WORDS:
        return "/returns"
    if c in GUIDE_WORDS:
        return "/guide"
    if c in ADMIN_WORDS:
        return "/admin"
    if c in DIGEST_WORDS:
        return "/digest"
    return c


# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════

_us = {}


def _st(cid):
    if cid not in _us:
        _us[cid] = {"page": 0, "sort": "score", "view": "today"}
    return _us[cid]


# ═══════════════════════════════════════════════════════════════
# TELEGRAM API HELPERS
# ═══════════════════════════════════════════════════════════════


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": PARSE_MODE,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage", data=data, timeout=10)
        if r.status_code != 200:
            print(f"[WARN] send {r.status_code}")
            with contextlib.suppress(Exception):
                print(f"[WARN] {r.json().get('description', '')[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[ERR] send: {e}")
        return False


def answer_cb(cid, text=""):
    with contextlib.suppress(Exception):
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/answerCallbackQuery",
            data={"callback_query_id": cid, "text": text},
            timeout=5,
        )


def get_updates(offset=None):
    p = {"timeout": 30, "allowed_updates": json.dumps(["message", "callback_query"])}
    if offset:
        p["offset"] = offset
    try:
        return requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates", params=p, timeout=35
        ).json()
    except Exception as e:
        print(f"[ERR] updates: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════


def kb_main(cp=0, tp=1, sort="score", view="today"):
    def dot(v):
        return "●" if view == v else "○"

    def sdot(s):
        return "●" if sort == s else "○"

    kb = [
        # Row 1 — Primary views
        [
            {"text": "✅ Buy setups", "callback_data": "view_prime"},
            {"text": f"{dot('today')} Today", "callback_data": "view_today"},
            {"text": f"{dot('new')} New", "callback_data": "view_new"},
            {"text": f"{dot('exit')} Exit", "callback_data": "view_exit"},
        ],
        # Row 2 — Secondary views (💼 Portfolio added)
        [
            {"text": f"{dot('caution')} Caution", "callback_data": "view_caution"},
            {"text": f"{dot('strong')} Strong", "callback_data": "view_strong"},
            {"text": "💼 Portfolio", "callback_data": "view_portfolio"},
            {"text": "Digest", "callback_data": "/digest"},
            {"text": "Help", "callback_data": "help"},
        ],
    ]

    # Sort row (only on today/list view)
    if view in ("today", "list"):
        kb.append(
            [
                {"text": f"{sdot('score')} Score", "callback_data": "sort_score"},
                {"text": f"{sdot('3m')} 3M", "callback_data": "sort_3m"},
                {"text": f"{sdot('top10')} Top10", "callback_data": "sort_top10"},
                {"text": "News", "callback_data": "news"},
                {"text": "Summary", "callback_data": "summary"},
            ]
        )

    # Pagination row
    if view == "today" and tp > 1:
        nav = []
        if cp > 0:
            nav.append({"text": "◀ Prev", "callback_data": "prev"})
        nav.append({"text": f"{cp + 1}/{tp}", "callback_data": "noop"})
        if cp < tp - 1:
            nav.append({"text": "Next ▶", "callback_data": "next"})
        kb.append(nav)

        s = max(0, min(cp - 2, tp - 5))
        e = min(tp, s + 5)
        kb.append([{"text": f"●{p + 1}" if p == cp else str(p + 1), "callback_data": f"page_{p}"} for p in range(s, e)])

    return {"inline_keyboard": kb}


def kb_prime():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Today", "callback_data": "view_today"},
                {"text": "👀 Watch", "callback_data": "view_today"},
            ],
            [
                {"text": "◀◀ Main", "callback_data": "view_today"},
                {"text": "❓ Help", "callback_data": "help"},
            ],
        ]
    }


def kb_portfolio():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Returns", "callback_data": "view_returns"},
                {"text": "📉 Exits", "callback_data": "view_exits"},
            ],
            [
                {"text": "🏠 Main Menu", "callback_data": "back_to_main"},
            ],
        ]
    }


def kb_back():
    return {"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "back_to_main"}]]}


def kb_guide():
    return {
        "inline_keyboard": [
            [{"text": "📖 Open full guide", "url": GUIDE_PDF_URL}],
            [{"text": "🏠 Main Menu", "callback_data": "back_to_main"}],
        ]
    }


def kb_admin():
    return {
        "inline_keyboard": [
            [
                {"text": "Health", "callback_data": "admin_health"},
                {"text": "Users", "callback_data": "admin_users"},
            ],
            [
                {"text": "Activity", "callback_data": "admin_stats"},
                {"text": "🏠 Main", "callback_data": "back_to_main"},
            ],
        ]
    }


def kb_card():
    return {
        "inline_keyboard": [
            [
                {"text": "◀ Back", "callback_data": "back_from_card"},
                {"text": "🏠 Main Menu", "callback_data": "back_to_main"},
            ]
        ]
    }


# ═══════════════════════════════════════════════════════════════
# COMMAND HANDLER
# ═══════════════════════════════════════════════════════════════


def handle_command(chat_id, text, is_cb=False, raw_user=None):
    cmd = (text or "").strip().lower()
    if "@" in cmd:
        cmd = cmd.split("@")[0]
    print(f"[CMD] {chat_id} {cmd!r} cb={is_cb}")

    if raw_user:
        track_user(FakeUser(raw_user))
        log_activity(raw_user.get("id", chat_id), "cb" if is_cb else "cmd", cmd)

    if raw_user and is_blocked(raw_user.get("id", 0)):
        return {"message": None, "keyboard": None} if is_cb else None

    res = load_scan_results()
    if not res:
        m = "No scan results found.\nPipeline runs at 6:00 AM IST daily."
        if is_cb:
            return {"message": m, "keyboard": None}
        send_message(chat_id, m)
        return None

    stocks = res["stocks"]
    ps = res["page_size"]
    sd = res["scan_date"]
    hist = load_history()
    st = _st(chat_id)

    def reply(m, kb=None):
        if is_cb:
            return {"message": m, "keyboard": kb}
        send_message(chat_id, m, reply_markup=kb)
        return None

    def today_page(pg, srt):
        ss = sort_stocks(stocks, srt)
        tp = max(1, (len(ss) + ps - 1) // ps)
        pg = max(0, min(pg, tp - 1))
        st["page"] = pg
        st["sort"] = srt
        st["view"] = "today"
        return reply(format_stock_list(ss, pg * ps, ps, sd), kb_main(pg, tp, srt, "today"))

    def view(vn, m, kb=None):
        st["view"] = vn
        return reply(m, kb or kb_main(0, 1, st["sort"], vn))

    # ── ROUTES ────────────────────────────────────────────────

    # ── START / WELCOME ───────────────────────────────────────
    if cmd == "/start":
        st["view"] = "today"
        st["page"] = 0
        st["sort"] = "score"
        user_name = raw_user.get("first_name", "") if raw_user else ""
        try:
            from nse_output import build_morning_keyboard, format_welcome_scan

            msg, kb = format_welcome_scan(user_name)
            return reply(msg, kb)
        except Exception:
            return reply(format_welcome(user_name or None), kb_main(0, 1, "score", "today"))

    # ── PRIME ─────────────────────────────────────────────────
    elif cmd in ("/prime", "view_prime"):
        st["view"] = "prime"
        return reply(format_prime_stocks(stocks, sd), kb_prime())

    # ── PORTFOLIO (NEW) ───────────────────────────────────────
    elif cmd in ("/portfolio", "view_portfolio"):
        st["view"] = "portfolio"
        return reply(format_portfolio(), kb_portfolio())

    elif cmd in ("/exits", "view_exits"):
        st["view"] = "exits"
        return reply(format_exits(), kb_portfolio())

    elif cmd in ("/returns", "view_returns"):
        st["view"] = "returns"
        return reply(format_returns(), kb_portfolio())

    # ── TODAY ─────────────────────────────────────────────────
    elif cmd in ("/today", "view_today", "back_to_main", "main_menu"):
        st["view"] = "today"
        st["page"] = 0
        user_name = raw_user.get("first_name", "") if raw_user else ""
        try:
            from nse_output import build_morning_keyboard, format_welcome_scan

            msg, kb = format_welcome_scan(user_name)
            return reply(msg, kb)
        except Exception:
            return reply(format_today_scan(stocks, sd), kb_main(0, 1, st["sort"], "today"))

    # ── PAGINATION ────────────────────────────────────────────
    elif cmd in ("/next", "next"):
        if st["view"] != "today":
            return today_page(0, st["sort"])
        ss = sort_stocks(stocks, st["sort"])
        tp = max(1, (len(ss) + ps - 1) // ps)
        if st["page"] + 1 >= tp:
            return reply("Last page!")
        return today_page(st["page"] + 1, st["sort"])

    elif cmd in ("/prev", "prev"):
        if st["view"] != "today":
            return today_page(0, st["sort"])
        if st["page"] == 0:
            return reply("First page!")
        return today_page(st["page"] - 1, st["sort"])

    elif cmd.startswith(("/page", "page_")):
        try:
            pn = int(cmd.split()[1]) - 1 if cmd.startswith("/page") else int(cmd.split("_")[1])
            return today_page(pn, st["sort"])
        except Exception:
            return reply("Usage: /page N")

    # ── SORT ──────────────────────────────────────────────────
    elif cmd == "sort_score":
        return today_page(0, "score")
    elif cmd == "sort_3m":
        return today_page(0, "3m")
    elif cmd == "sort_top10":
        return today_page(0, "top10")
    elif cmd == "noop":
        return {"message": None, "keyboard": None} if is_cb else None

    # ── NEW ───────────────────────────────────────────────────
    elif cmd in ("/new", "view_new"):
        if len(hist) < 2:
            return view(
                "new",
                f"{_b('History Building...')}\n"
                f"Need 2+ days. Have: {len(hist)} day(s)\n"
                f"Check back tomorrow after 6 AM scan.",
            )
        return view("new", format_new_stocks(get_new_stocks(hist), sd))

    # ── EXIT ──────────────────────────────────────────────────
    elif cmd in ("/exit", "view_exit"):
        if len(hist) < 2:
            return view("exit", f"{_b('History Building...')}\nNeed 2+ days. Have: {len(hist)} day(s)")
        return view("exit", format_exit_stocks(get_exit_stocks(hist), sd))

    # ── CAUTION ───────────────────────────────────────────────
    elif cmd in ("/caution", "view_caution"):
        return view("caution", format_caution_stocks(stocks, sd))

    # ── STRONG / HOLD AND TRAIL ───────────────────────────────
    elif cmd in ("/strong", "view_strong"):
        if len(hist) < 5:
            return view(
                "strong",
                f"💰 {_b('Hold & Trail')}\n"
                f"Needs 5 days history. Have: {len(hist)}. "
                f"Ready in: {5 - len(hist)} more day(s)",
            )
        return view("strong", format_strong_stocks(get_strong_stocks(hist), sd))

    # ── NEWS ──────────────────────────────────────────────────
    elif cmd in ("/news", "news"):
        ss = sort_stocks(stocks, st["sort"])
        tp = max(1, (len(ss) + ps - 1) // ps)
        pg = max(0, min(st["page"], tp - 1))
        return reply(format_stock_list(ss, pg * ps, ps, sd, include_news=True), kb_main(pg, tp, st["sort"], "today"))

    # ── LIST / SUMMARY ────────────────────────────────────────
    elif cmd in ("/list", "list", "summary"):
        return view("today", format_summary(stocks, sd, hist))

    # ── HELP ──────────────────────────────────────────────────
    elif cmd in ("/help", "help"):
        return reply(format_help(), kb_main(st["page"], 1, st["sort"], st["view"]))

    # ── GUIDE ─────────────────────────────────────────────────
    elif cmd in ("/guide", "guide"):
        m = format_guide_message() if _ADMIN_OK else f"{_b('NSE Scanner Guide')}\nTap below for the full guide."
        return reply(m, kb_guide())

    # ── SIGNAL CARD ───────────────────────────────────────────
    elif cmd.startswith("stock_") and not cmd.startswith("stock_news_"):
        sym = cmd.replace("stock_", "").upper()
        m = format_signal_card(sym) if _TRACKER_OK else f"Tracker not available for {_code(sym)}"
        return reply(m, kb_card())

    elif cmd == "back_from_card":
        st["view"] = "today"
        st["page"] = 0
        user_name = raw_user.get("first_name", "") if raw_user else ""
        try:
            from nse_output import build_morning_keyboard, format_welcome_scan

            msg, kb = format_welcome_scan(user_name)
            return reply(msg, kb)
        except Exception:
            return reply(format_today_scan(stocks, sd), kb_main(0, 1, st["sort"], "today"))

    # ── DIGEST ────────────────────────────────────────────────
    elif cmd == "/digest":
        if not _DIGEST_OK:
            return reply("Weekly digest module not available.")
        try:
            today = date.today()
            days_since = (today.weekday() - 4) % 7
            if days_since == 0 and today.weekday() != 4:
                days_since = 7
            last_friday = today - timedelta(days=days_since)
            week_dates = get_week_dates(last_friday)
            week_hist = get_week_history(hist, week_dates)

            if not week_hist:
                return reply(
                    f"📅 {_b('Weekly Digest')}\n\n"
                    f"No scan history for last week yet.\n"
                    f"Need at least 2 trading days of history.\n"
                    f"Currently have: {len(hist)} day(s)"
                )

            week_prices = {}
            try:
                conn = sqlite3.connect(getattr(config, "DB_PATH", "nse_scanner.db"))
                all_syms = set()
                for d in week_hist:
                    all_syms.update(d.get("symbols", []))
                week_prices = get_week_prices(list(all_syms), week_dates, conn)
                conn.close()
            except Exception:
                pass

            analysis = analyze_week(week_hist, week_prices)
            m = format_weekly_digest(analysis, week_dates)
            return reply(m, kb_back())

        except Exception as e:
            log.exception(f"Digest error: {e}")
            return reply(f"Digest error: {e}")

    # ── ADMIN ─────────────────────────────────────────────────
    elif cmd in ("/admin", "admin_health"):
        if not _ADMIN_OK or not (raw_user and is_admin(raw_user.get("id", 0))):
            return reply("Admin access only.")
        return reply(format_health_report(generate_health_report()), kb_admin())

    elif cmd in ("/users", "admin_users"):
        if not _ADMIN_OK or not (raw_user and is_admin(raw_user.get("id", 0))):
            return reply("Admin access only.")
        return reply(format_user_list(), kb_admin())

    elif cmd == "/health":
        if _ADMIN_OK and raw_user and is_admin(raw_user.get("id", 0)):
            send_message(chat_id, format_health_report(generate_health_report()), reply_markup=kb_admin())
        else:
            send_message(chat_id, "Admin access only.")
        return None

    elif cmd == "admin_stats":
        if _ADMIN_OK and raw_user and is_admin(raw_user.get("id", 0)):
            from nse_bot_admin import get_activity_stats

            s = get_activity_stats(days=1)
            m = (
                f"{_b('Activity Stats (Today)')}\n\n"
                f"Total actions: {s['total_actions']}\n"
                f"Unique users: {s['unique_users']}\n"
            )
            if s.get("top_actions"):
                m += f"\n{_b('Top Actions:')}\n"
                for a, c in s["top_actions"][:8]:
                    m += f"  {_code(a)}: {c}\n"
            return reply(m, kb_admin())
        return reply("Admin access only.")

    # ── BROADCAST ─────────────────────────────────────────────
    elif cmd == "/broadcast":
        if not (_ADMIN_OK and raw_user and is_admin(raw_user.get("id", 0))):
            return reply("Admin access only.")
        try:
            from nse_bot_admin import get_user_count

            ucount = get_user_count()
        except Exception:
            ucount = 0
        scan_summary = ""
        try:
            import json as _json
            from pathlib import Path as _Path

            _sf = _Path("telegram_last_scan.json")
            if _sf.exists():
                _d = _json.loads(_sf.read_text())
                _stocks = _d.get("stocks", [])
                _prime = sum(1 for s in _stocks if s.get("situation") == "prime")
                _sd = _d.get("scan_date", "")
                scan_summary = f"\n\n📊 Today's scan: <b>{len(_stocks)} stocks</b> · 🎯 <b>{_prime} Prime</b> · {_sd}"
        except Exception:
            pass

        confirm_msg = (
            f"📢 {_b('Broadcast Confirmation')}\n\n"
            f"This will send today's full scan to "
            f"<b>{ucount} registered users</b>.{scan_summary}\n\n"
            f"⚠️ Are you sure?"
        )
        confirm_kb = {
            "inline_keyboard": [
                [
                    {"text": "✅ YES — Send Now", "callback_data": "broadcast_confirm"},
                    {"text": "❌ Cancel", "callback_data": "back_to_main"},
                ]
            ]
        }
        return reply(confirm_msg, confirm_kb)

    elif cmd == "broadcast_confirm":
        if not (_ADMIN_OK and raw_user and is_admin(raw_user.get("id", 0))):
            return reply("Admin access only.")
        try:
            from nse_bot_admin import broadcast_to_all_users, format_broadcast_summary

            result = broadcast_to_all_users(skip_chat_id=int(chat_id))
            summary = format_broadcast_summary(result)
            return reply(summary, kb_admin())
        except Exception as e:
            log.exception(f"Broadcast error: {e}")
            return reply(f"❌ Broadcast failed: {_code(str(e))}", kb_admin())

    # ── Unknown ───────────────────────────────────────────────
    else:
        return reply(
            f"Didn't understand: {_code(cmd)}\n\n"
            f"Try: {_b('/prime')}, {_b('/today')}, {_b('/new')}, "
            f"{_b('/exit')}, {_b('/strong')}, {_b('/caution')},\n"
            f"{_b('/portfolio')}, {_b('/returns')}, {_b('/exits')}, "
            f"{_b('/digest')}, {_b('/help')}",
            kb_main(st["page"], 1, st["sort"], st["view"]),
        )


# ═══════════════════════════════════════════════════════════════
# UPDATE PROCESSOR
# ═══════════════════════════════════════════════════════════════


def process_update(upd):
    try:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            cid = str(cq["message"]["chat"]["id"])
            answer_cb(cq["id"])
            r = handle_command(cid, cq.get("data", ""), is_cb=True, raw_user=cq.get("from", {}))
            if isinstance(r, dict) and r.get("message"):
                send_message(cid, r["message"], reply_markup=r.get("keyboard"))

        elif "message" in upd:
            mo = upd["message"]
            cid = str(mo["chat"]["id"])
            t = mo.get("text", "").strip()
            if not t:
                return
            print(f"[MSG] {cid} {t!r}")
            rc = resolve_text_to_command(t)
            print(f"[RES] {rc!r}")
            handle_command(cid, rc, is_cb=False, raw_user=mo.get("from", {}))

    except Exception as e:
        import traceback

        print(f"[ERR] {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
# HEALTH SCHEDULER
# ═══════════════════════════════════════════════════════════════


def health_scheduler():
    if not _ADMIN_OK:
        return
    log.info("[SCHED] Health check 11:30 PM daily")
    last = None
    while True:
        try:
            now = datetime.now()
            if now.hour == 23 and 30 <= now.minute < 32 and last != now.date():
                send_health_check()
                last = now.date()
            time.sleep(60)
        except Exception:
            time.sleep(60)


# ═══════════════════════════════════════════════════════════════
# STARTUP CHECKS
# ═══════════════════════════════════════════════════════════════


def startup_checks():
    ok = True

    try:
        r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getMe", timeout=5).json()
        if r.get("ok"):
            print(f"[OK] Bot: @{r['result']['username']}")
        else:
            print("[FAIL] Token invalid")
            ok = False
    except Exception:
        ok = False

    try:
        wh = (
            requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getWebhookInfo", timeout=5)
            .json()
            .get("result", {})
            .get("url", "")
        )
        if wh:
            print(f"[WARN] Webhook active: {wh}")
            print("[WARN] Delete webhook to use polling mode")
            ok = False
        else:
            print("[OK] No webhook — polling mode ready")
    except Exception:
        pass

    r = load_scan_results()
    if r:
        stocks = r.get("stocks", [])
        sit_counts = {}
        for s in stocks:
            sit = s.get("situation", "watch")
            sit_counts[sit] = sit_counts.get(sit, 0) + 1
        prime = sit_counts.get("prime", 0)
        print(f"[OK] {len(stocks)} stocks (date: {r['scan_date']}) | 🎯 {prime} prime")
    else:
        print("[FAIL] No scan data")
        ok = False

    h = load_history()
    print(f"[OK] History: {len(h)} day(s)")

    # Portfolio status
    try:
        from nse_portfolio import get_portfolio_summary

        ps = get_portfolio_summary()
        print(f"[OK] Portfolio: {ps['open_count']} open | {ps['closed_count']} closed | win rate {ps['win_rate']}%")
    except ImportError:
        print("[WARN] nse_portfolio.py not found — /portfolio disabled")
    except Exception as e:
        print(f"[WARN] Portfolio check failed: {e}")

    print(f"[OK] Admin: {_ADMIN_OK} | Tracker: {_TRACKER_OK} | Digest: {_DIGEST_OK}")

    if _ADMIN_OK:
        print(f"[OK] Users: {get_user_count()}")
    if _TRACKER_OK:
        ts = get_tracker_summary()
        print(
            f"[OK] Signals: {ts.get('total_active', 0)} active, "
            f"{ts.get('total_exited', 0)} exited, "
            f"🎯 {ts.get('prime_count', 0)} prime"
        )

    return ok


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════


def main():
    print("=" * 55)
    print("  NSE Scanner Bot — Phase 2.3.1 (Portfolio added)")
    print("  Commands: Prime/Today/New/Exit/Caution/Strong")
    print("  Portfolio: /portfolio /returns /exits")
    print("=" * 55 + "\n")

    if not startup_checks():
        print("[BOT] Fix issues then restart")
        return

    threading.Thread(target=health_scheduler, daemon=True).start()
    if _ADMIN_OK:
        print("[BOT] Health scheduler running (11:30 PM daily)")

    print("\n[BOT] Ready! Listening for messages...\n")

    offset = None
    while True:
        try:
            u = get_updates(offset)
            if u and u.get("ok") and u.get("result"):
                for upd in u["result"]:
                    process_update(upd)
                    offset = upd["update_id"] + 1
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n[BOT] Stopped")
            break
        except Exception as e:
            print(f"[ERR] {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
