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
config.py — Project Configuration (v2 — Situation Engine + Filters)
====================================================================
WHAT CHANGED:
  Added Section 3: Situation Engine constants
  Added Section 4: Enhanced filter thresholds
  Everything above DHAN_TOKEN is unchanged — paste BELOW it
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Folder Paths ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NSE_DATA_DIR = os.path.join(BASE_DIR, "nse_data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(BASE_DIR, "nse_scanner.db")

# ── Scanner Filter Thresholds (v2 — enhanced) ─────────────────
MIN_PRICE = 50
MIN_MARKET_CAP = 500  # ₹500 Cr minimum — now ENFORCED
MIN_VOLUME = 50000
MIN_DELIVERY = 35
MIN_TURNOVER = 200  # NEW: ₹2 Cr daily turnover (turnover_lacs ≥ 200)
MAX_ANNVOL = 1.5
MAX_PE = 80
TOP_N_STOCKS = 25

# ── Return Calculation (display only — not used for ranking) ──
WEIGHT_1M = 0.20
WEIGHT_2M = 0.30
WEIGHT_3M = 0.50

DAYS_1M = 22
DAYS_2M = 44
DAYS_3M = 66

# ── Legacy Bonus Score ─────────────────────────────────────────
BONUS_52W_HIGH = 0.05
BONUS_TOP25 = 0.03

# ── API Keys ──────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHATID = os.getenv("TELEGRAM_CHAT_ID")

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

# ═════════════════════════════════════════════════════════════
# SECTION 2 — CATEGORY / BUCKET SYSTEM (existing — unchanged)
# ═════════════════════════════════════════════════════════════

HISTORY_DAYS = 30
STRONG_PICK_MIN_DAYS = 5

CATEGORY_ORDER = ["uptrend", "rising", "peak", "safer", "recovering"]

RECOVERING_MARGIN = 0.02
RECOVERING_3M_CEILING = 0.10
SAFER_DELIVERY_MIN = 55.0
SAFER_SCORE_MIN = 6
PEAK_52W_PCT = 0.90

BOT_PAGE_SIZE = 5
TELEGRAM_CHAR_LIMIT = 4000

# ═════════════════════════════════════════════════════════════
# SECTION 3 — SITUATION ENGINE (NEW)
# ═════════════════════════════════════════════════════════════

# Situation labels — used throughout bot + handler + tracker
SITUATION_PRIME = "prime"  # 🎯 Enter today
SITUATION_WATCH = "watch"  # 👀 Monitor — not today
SITUATION_HOLD = "hold"  # 💰 Already in move — trail SL
SITUATION_BOOK = "book"  # ⚠️ Mature move — protect gains
SITUATION_AVOID = "avoid"  # 🚫 Skip completely

# Display metadata for each situation
SITUATION_META = {
    "prime": {
        "icon": "🎯",
        "label": "Prime Entry",
        "action": "Enter today — confirm on TradingView",
        "color": "green",
    },
    "watch": {
        "icon": "👀",
        "label": "Watch Closely",
        "action": "Good setup — one condition missing. Check tomorrow.",
        "color": "blue",
    },
    "hold": {
        "icon": "💰",
        "label": "Hold & Trail",
        "action": "Already in a move — trail your stop loss up.",
        "color": "yellow",
    },
    "book": {
        "icon": "⚠️",
        "label": "Book Profits",
        "action": "Move is maturing — consider booking 50-100%.",
        "color": "orange",
    },
    "avoid": {
        "icon": "🚫",
        "label": "Avoid Now",
        "action": "Weak setup or bearish signal — skip today.",
        "color": "red",
    },
}

# Priority order for display (most actionable first)
SITUATION_ORDER = ["prime", "hold", "watch", "book", "avoid"]

# Score thresholds for situation assignment
SITUATION_PRIME_MIN_SCORE = 7  # score ≥ 7 + fresh cross + not overextended
SITUATION_WATCH_MIN_SCORE = 4  # score 4-6
SITUATION_HOLD_MIN_STREAK = 5  # in list 5+ days = hold and trail
SITUATION_BOOK_CROSS_AGE = 30  # cross > 30 days = move maturing
SITUATION_BOOK_DIST_PCT = 15.0  # >15% above HMA55 = stretched
SITUATION_AVOID_MAX_SCORE = 3  # score ≤ 3 = avoid

# ═════════════════════════════════════════════════════════════
# SECTION 4 — PROBABILITY MODEL CONSTANTS
# ═════════════════════════════════════════════════════════════

# Base probability before any bonuses
PROB_BASE = 40

# Score bonuses
PROB_SCORE_PRIME = 25  # score ≥ 7
PROB_SCORE_HIGH = 20  # score ≥ 6 (was PROB_SCORE_HIGH)
PROB_SCORE_MED = 10  # score ≥ 4

# Freshness bonuses (NEW)
PROB_FRESH_CROSS = 15  # cross ≤ 10 days
PROB_YOUNG_CROSS = 8  # cross 11-20 days

# Room to run bonuses (NEW)
PROB_ROOM_TIGHT = 10  # dist ≤ 5% from HMA55
PROB_ROOM_OK = 5  # dist 5-10%

# Streak bonuses (existing)
PROB_STREAK_5 = 10
PROB_STREAK_10 = 15

# Category bonuses (existing)
PROB_CAT_UPTREND = 8
PROB_CAT_RISING = 6
PROB_CAT_SAFE = 4

# T2 discount (existing)
PROB_T2_DISCOUNT = 16

# Penalties (NEW)
PROB_PENALTY_OVEREXT = -15  # >15% stretched
PROB_PENALTY_BOOK = -10  # BOOK PROFITS situation
PROB_PENALTY_AVOID = -20  # AVOID situation
