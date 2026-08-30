"""
Indian Market State Machine & Tick Size Rounding Module (EQATS Institutional Integration).

Enforces Indian Stock Market (NSE/BSE) trading session boundaries in Asia/Kolkata timezone (IST):
- Market Hours: 09:15 AM to 03:30 PM IST, Monday through Friday.
- Pre-Market: 09:00 AM to 09:15 AM IST.
- Intraday (MIS) Cutoff: Past 03:00 PM IST, new MIS orders are BLOCKED and active MIS positions
  trigger a trailing exit strategy / square-off to prevent broker penalty fees.
- Indian Standard Tick Size: Prices strictly rounded to 0.05 INR increments.
"""

import math
import logging
from datetime import datetime, time as dt_time, timedelta, timezone
from enum import Enum
from typing import Dict, Any, Optional, Tuple

_log = logging.getLogger("IndianMarketStateMachine")

# IST is UTC + 5:30
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
INDIAN_TICK_SIZE = 0.05  # Standard 0.05 INR tick size for Indian exchanges


def round_to_indian_tick_size(price: float, tick_size: float = INDIAN_TICK_SIZE) -> float:
    """
    Rounds a price strictly to the Indian exchange standard tick size (default: 0.05 INR).
    Example:
        2850.12 -> 2850.10
        2850.13 -> 2850.15
        2850.18 -> 2850.20
    """
    if not math.isfinite(price) or price <= 0:
        return 0.0
    num_ticks = round(price / tick_size)
    rounded = round(num_ticks * tick_size, 2)
    return rounded


class IndianMarketState(Enum):
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    OPEN = "OPEN"
    INTRADAY_CUTOFF = "INTRADAY_CUTOFF"  # Past 3:00 PM IST: MIS entries blocked, square-off active
    POST_MARKET = "POST_MARKET"


class IndianMarketStateMachine:
    """
    State Machine governing Indian Exchange (NSE/BSE) trading session rules and safeguards.
    """

    # Session boundaries in IST (24-hour format)
    PRE_MARKET_START = dt_time(9, 0)
    MARKET_OPEN = dt_time(9, 15)
    INTRADAY_CUTOFF = dt_time(15, 0)    # 3:00 PM IST
    MARKET_CLOSE = dt_time(15, 30)      # 3:30 PM IST
    POST_MARKET_CLOSE = dt_time(16, 0)

    @classmethod
    def get_current_ist_time(cls) -> datetime:
        """Returns current datetime in Asia/Kolkata (IST) timezone."""
        return datetime.now(IST_TIMEZONE)

    @classmethod
    def get_market_state(cls, dt_ist: Optional[datetime] = None) -> IndianMarketState:
        """
        Determines current Indian market state for given IST datetime (defaults to current IST time).
        """
        now = dt_ist or cls.get_current_ist_time()

        # Weekends (Saturday=5, Sunday=6)
        if now.weekday() >= 5:
            return IndianMarketState.CLOSED

        t = now.time()

        if t < cls.PRE_MARKET_START:
            return IndianMarketState.CLOSED
        elif cls.PRE_MARKET_START <= t < cls.MARKET_OPEN:
            return IndianMarketState.PRE_MARKET
        elif cls.MARKET_OPEN <= t < cls.INTRADAY_CUTOFF:
            return IndianMarketState.OPEN
        elif cls.INTRADAY_CUTOFF <= t < cls.MARKET_CLOSE:
            return IndianMarketState.INTRADAY_CUTOFF
        elif cls.MARKET_CLOSE <= t < cls.POST_MARKET_CLOSE:
            return IndianMarketState.POST_MARKET
        else:
            return IndianMarketState.CLOSED

    @classmethod
    def is_market_open(cls, dt_ist: Optional[datetime] = None) -> bool:
        """Returns True if market is currently within regular trading hours (09:15 AM - 03:30 PM IST)."""
        state = cls.get_market_state(dt_ist)
        return state in (IndianMarketState.OPEN, IndianMarketState.INTRADAY_CUTOFF)

    @classmethod
    def is_mis_entry_allowed(cls, dt_ist: Optional[datetime] = None) -> bool:
        """
        Returns True if intraday MIS order entry is allowed (09:15 AM to 03:00 PM IST, Mon-Fri).
        Past 03:00 PM IST, MIS order entry is strictly BLOCKED.
        """
        state = cls.get_market_state(dt_ist)
        return state == IndianMarketState.OPEN

    @classmethod
    def should_trigger_mis_squareoff(cls, dt_ist: Optional[datetime] = None) -> bool:
        """
        Returns True if past 03:00 PM IST cut-off time on trading days,
        signaling that active MIS intraday positions must trigger trailing exits / square-off.
        """
        state = cls.get_market_state(dt_ist)
        return state == IndianMarketState.INTRADAY_CUTOFF

    @classmethod
    def validate_order_execution(
        cls,
        symbol: str,
        order_type: str,
        product: str = "CNC",
        price: float = 0.0,
        dt_ist: Optional[datetime] = None,
    ) -> Tuple[bool, str, float]:
        """
        Validates order submission against market session rules and applies 0.05 INR tick rounding.

        Returns:
            Tuple[bool, str, float]: (allowed: bool, reason: str, rounded_price: float)
        """
        now = dt_ist or cls.get_current_ist_time()
        state = cls.get_market_state(now)
        product_upper = str(product).strip().upper() if product else "CNC"
        rounded_price = round_to_indian_tick_size(price) if price > 0 else 0.0

        if state == IndianMarketState.CLOSED:
            return False, f"Indian stock market is CLOSED ({now.strftime('%A %H:%M IST')}).", rounded_price

        if state == IndianMarketState.PRE_MARKET:
            return False, f"Indian stock market is in PRE_MARKET session ({now.strftime('%H:%M IST')}). Orders restricted.", rounded_price

        if state == IndianMarketState.POST_MARKET:
            return False, f"Indian stock market is in POST_MARKET session ({now.strftime('%H:%M IST')}).", rounded_price

        # State is OPEN or INTRADAY_CUTOFF
        if product_upper == "MIS" and state == IndianMarketState.INTRADAY_CUTOFF:
            _log.warning(
                "MIS Intraday order blocked for %s past 03:00 PM IST cutoff (%s). Hard stop safeguard active.",
                symbol,
                now.strftime("%H:%M:%S IST"),
            )
            return False, "MIS Intraday orders blocked past 03:00 PM IST cutoff. Trailing exit safeguard active.", rounded_price

        return True, "Order validated for Indian market session.", rounded_price


# Global singleton instance
global_indian_state_machine = IndianMarketStateMachine()
