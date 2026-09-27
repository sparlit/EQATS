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


"""Frozen selected settings. Scope is forward PAPER only."""
from portfolio_accounting.ledger import LedgerConfig

PROFILE_ID = "LADDER_DAILY_20260922"
VOLUME_MULTIPLE = 1.8
RSI_LOWER = 50
RSI_UPPER = 70
SCORE_MIN = 65
EXPIRY_SESSIONS = 5
EXCLUDED_SYMBOLS = {"UNITDSPR"}
CONFIG = LedgerConfig(fee_bps=10, slippage_bps=5)
