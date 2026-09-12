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
Central strategy configuration.

EVERY tunable parameter for the swing strategy lives here.
To change behavior: edit ONE value in this file, restart the service.
No other file needs to be touched.

Sections:
  SETUP       — Gabani pullback detection thresholds
  SCREENER    — Stage-2 baseline + liquidity filters
  BACKTEST    — walk-forward simulator parameters
  REGIME      — market regime spectrum thresholds
  ALL_WEATHER — defensive-regime reversal detection
  SIZING      — capital allocation

Note: this is a *measuring tool* config, not a recommendation set.
The owner decides what values to use based on their own research.
"""

# ============================================================
# SETUP — Gabani pullback detection (setup.py)
# ============================================================
SETUP = {
    "IMPULSE_LOOKBACK": 90,
    "IMPULSE_MIN_PCT": 0.18,  # v3.2: was 0.25
    "IMPULSE_MAX_PCT": 0.75,  # v3.2: was 0.50
    "EMA10_BREAK_TOL": 0.45,  # v3.3: was 0.35, v3.2: 0.25
    "PB_LOOKBACK": 25,
    "PB_MIN_PCT": 0.06,  # v3.3: was 0.08, v3.2: 0.12
    "PB_MAX_PCT": 0.25,  # v3.2: was 0.20
    "PB_MIN_DAYS": 6,
    "PB_MAX_DAYS": 20,  # v3.3: was 15
    "CRASH_WINDOW": 3,
    "CRASH_MAX_PCT": 0.15,
    "EMA10": 10,
    "EMA20": 20,
    "EMA_TOUCH_MULT": 0.03,
    "VOL_SMA_DAYS": 20,
    "TIGHT_ATR_MULT": 0.9,
    "TIGHT_MAX_RUN_BACK": 4,
    "TIGHT_MIN": 2,
    "MAX_STOP_PCT": 0.05,
    "TARGET_R_MULTIPLE": 3.0,  # measuring reference; owner decides
    "MAX_SHIFT": 2,
}

# ============================================================
# SCREENER — Stage-2 baseline + liquidity (scanner.py)
# ============================================================
SCREENER = {
    "EMA200": 200,
    "MIN_HISTORY": 220,
    "MOM_1M_MIN": 0.20,
    "MOM_3M_MIN": 0.30,
    "HIGH_52WK_MIN_RATIO": 0.75,
    "VOL_EXPLOSION_MULT": 2.5,
    "VOL_LOOKBACK": 60,
    "LIQ_DAYS": 20,
    "MIN_AVG_TURNOVER": 2e7,  # ₹2 cr average daily turnover
}

# ============================================================
# BACKTEST — walk-forward simulator (backtest.py)
# ============================================================
BACKTEST = {
    "HOLD_DAYS_MAX": 30,
    "ORDER_EXPIRY_BARS": 3,
    "TICK_SIZE": 0.05,
    "TARGET_R": 3.0,  # default R for measurement
    "TRANCHES_ENABLED": False,
    "T_LEVEL_1": 2.0,
    "T_LEVEL_2": 3.0,
    "T_PCT_1": 0.33,
    "T_PCT_2": 0.33,
    "TRAIL_EMA": 10,
    "INITIAL_CAPITAL": 1_000_000,
    "SLIPPAGE_PCT": 0.001,
    "COMMISSION_PCT": 0.0005,
    "MAX_POSITIONS": 5,
    "MAX_PENDING_ORDERS": 20,
}

# ============================================================
# REGIME — spectrum classification (regime_spectrum.py)
# ============================================================
REGIME = {
    "STRONG_BULL_DIST_MIN": 0.02,  # 2% above EMA10
    "STRONG_BULL_BREADTH_MIN": 0.60,
    "EMA_PERIOD": 10,
    "EMA20_PERIOD": 20,
    "INDEX_CANDIDATES": ["^CNXSMALLCAP", "^CNXSC", "NIFTY_SMALLCAP_100.NS", "^NSEI"],
}

# ============================================================
# ALL_WEATHER — defensive-regime reversal detection (all_weather.py)
# ============================================================
ALL_WEATHER = {
    "BELOW_52W_MIN": 0.25,
    "NEAR_LOW_MAX": 0.15,
    "MAX_RISK_PCT": 0.05,
    "TARGET_R": 3.0,
    "TICK": 0.05,
}

# ============================================================
# SIZING — capital allocation (sizing.py)
# ============================================================
SIZING = {
    "B_PAYOFF": 3.0,
    "MAX_ALLOC": 0.25,
    "RISK_PER_TRADE": 0.01,
    "DEFAULT_CAPITAL": 1_000_000,
    "FALLBACK_WINRATE": 0.35,
    # shape_score -> multiplier, first match wins (descending)
    "QUALITY_TIERS": [
        (80, 1.20),
        (60, 1.00),
        (40, 0.80),
        (0, 0.60),
    ],
}


def dump():
    """Print entire config for inspection."""
    import json

    print(
        json.dumps(
            {
                "SETUP": SETUP,
                "SCREENER": SCREENER,
                "BACKTEST": BACKTEST,
                "REGIME": REGIME,
                "ALL_WEATHER": ALL_WEATHER,
                "SIZING": SIZING,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        dump()
    else:
        dump()
