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
settings.py
Centralized scanner configuration. Tunable thresholds live here so they can be
adjusted without touching scanner.py / module code.
"""

# Universe
UNIVERSE_DEFAULT_TOP_N = 500  # default top-N-by-market-cap tier (Nifty 100/200/500)
UNIVERSE_DEFAULT_WORKERS = 8  # default thread-pool size for per-stock evaluation
UNIVERSE_DEFAULT_SLEEP_BETWEEN_CALLS = 0.3  # seconds, per-yfinance-call courtesy delay

# Hard gate thresholds (non-negotiable safety filters)
MIN_F_SCORE = 6  # relaxed from spec ">7" — see README
MIN_DELIVERY_VALUE_INR = (
    5_00_00_000  # Rs 5 crore, latest available trading day (only used when delivery_kind == "actual")
)
MIN_HOLDINGS_CONVICTION_PCT = 50  # promoter + FII + DII > 50%

# Liquidity Adequacy hard gate: 20d average traded value (volume × close) floor.
# This is the replacement for the single-day traded-value proxy. Two times the old
# delivery floor because traded value is typically 2-3x real delivery; calibrated
# against Nifty 500 mid-cap names.
MIN_ADV_VALUE_INR = 10_00_00_000  # Rs 10 crore
ADV_LOOKBACK_SESSIONS = 20
ADV_MIN_SESSIONS = 15  # allow short histories (IPO, new listing)

# Secondary floor when the real-delivery path satisfies the gate: require
# ADV at least 30% of MIN_ADV_VALUE_INR. Prevents a thinly traded name from
# passing via a single high-delivery day (block deal / closing-auction spike).
MIN_ADV_SECONDARY_FLOOR_INR = 3_00_00_000  # Rs 3 crore

# Per-universe ADV outlier hard ceiling. yfinance occasionally surfaces
# multi-100x volume spikes on the first session after suspension/resumption;
# clamping protects the gate and the UI from a single outlier distorting
# the PASS list. The ceiling is well above any legitimate 20d ADV for the
# Nifty 500 universe (largest names average ~₹1000cr ADV).
ADV_HARD_CEILING_INR = 5_000_00_00_000  # Rs 5000 crore

# Hard gate windows (technical)
DRAWDOWN_LOWER_PCT = -40.0
DRAWDOWN_UPPER_PCT = -15.0
RSI_LOWER = 25
RSI_UPPER = 40

# Corporate action lookback
CORPORATE_ACTION_LOOKAHEAD_DAYS = 30

# Soft score weights — sum to 1.0. See README/methodology for rationale.
# `conviction_holding` activates once holdings data is wired in.
# Bump SCORE_VERSION whenever WEIGHTS changes: snapshots stamp it per row
# (scanner.to_json_records) so the tracker can attribute score-regime
# changes to a date. Promotion protocol: docs/feedback + evaluate_feedback.
WEIGHTS = {
    "valuation_compression": 0.20,
    "oversold_positioning": 0.15,
    "support_proximity": 0.15,
    "drawdown_sweetspot": 0.10,
    "volume_capitulation": 0.10,
    "quality_composite": 0.20,
    "conviction_holding": 0.10,
}

SCORE_VERSION = "weights-2026-06-v1"

# Scheduled scan windows — SINGLE SOURCE OF TRUTH for the twice-daily cadence.
# Consumed by:
#   - scan.yml's "Write scan_status.json" heredoc (imports this module)
#   - backend/scripts/check_cron_consistency.py (CI guard vs the YAML crons)
#   - backend/scripts/watchdog_check.py (next-expected-window staleness logic)
# If you change the cron schedule in .github/workflows/scan.yml, change it here
# in the same commit — the CI guard fails until both agree.
SCAN_WINDOWS_UTC = [(3, 30), (10, 30)]  # (hour_utc, minute_utc), Mon-Fri

# Source-cache TTLs (seconds)
HOLDINGS_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30 * 3  # ~90 days (quarterly-ish)
BHAVCOPY_CACHE_TTL_SECONDS = 60 * 60 * 12  # half a day
SURVEILLANCE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # weekly
CORPORATE_ACTIONS_CACHE_TTL_SECONDS = 60 * 60 * 12  # half a day
YF_CACHE_TTL_SECONDS = 60 * 60 * 12  # 12 h for yfinance-derived fields (price-dependent)
YF_FUNDAMENTAL_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 h for F-score (balance-sheet-quarterly)

# Stale-data threshold for the UI (hours)
STALE_DATA_HOURS = 18

# ATR / entry / target parameters
ATR_PERIOD = 14
ENTRY_ZONE_ATR_FRACTION = 0.5
STOP_LOSS_ATR_MULT = 1.0
TARGET_1_ATR_MULT = 1.5
TARGET_2_ATR_MULT = 2.5
