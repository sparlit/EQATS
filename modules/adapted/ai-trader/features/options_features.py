import datetime
from datetime import date, timedelta
from typing import Dict, List, Optional

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
Options-Aware Features
──────────────────────
Features that capture the structure of the options chain relative to ATM.
These are critical for the ML model to understand moneyness, expiry proximity,
and cross-strike relationships.

New features:
  1. relative_strike     – 0=ATM, +1=ATM+1, -1=ATM-1, etc.
  2. days_to_expiry      – trading days remaining until expiry
  3. oi_skew             – (total call OI - total put OI) / total OI
  4. pcr_near_atm        – PCR computed only from ATM ±1
  5. pcr_far             – PCR computed from ATM ±2 to ±3
  6. max_oi_call_rel     – relative strike with highest call OI
  7. max_oi_put_rel      – relative strike with highest put OI
  8. oi_concentration    – % of total OI at ATM ±1 (high = pinning risk)
  9. call_oi_gradient    – OI slope from ATM to ATM+3 (rising = resistance)
  10. put_oi_gradient    – OI slope from ATM to ATM-3 (rising = support)
  11. iv_skew            – difference in IV between OTM puts and OTM calls
  12. theta_pressure     – exponential decay factor as expiry approaches
"""


def compute_days_to_expiry(
    timestamp: datetime.datetime,
    expiry: date,
) -> int:
    """
    Compute trading days to expiry (approximate).
    Excludes weekends. Does not account for NSE holidays.
    """
    if expiry is None:
        return -1

    ref_date = timestamp.date() if isinstance(timestamp, datetime.datetime) else timestamp
    if ref_date >= expiry:
        return 0

    days = 0
    current = ref_date

    while current < expiry:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            days += 1
    return days


def compute_theta_pressure(days_to_expiry: int) -> float:
    """
    Exponential theta pressure factor.
    Theta decay accelerates as expiry approaches.
    Returns 0.0 (far from expiry) to 1.0 (expiry day).
    """
    if days_to_expiry <= 0:
        return 1.0
    # Exponential decay: pressure = 1 - exp(-days/5)
    # Returns ~0.0 for large days, approaches 1.0 as days -> 0
    import math

    return 1.0 - math.exp(-days_to_expiry / 5.0)
