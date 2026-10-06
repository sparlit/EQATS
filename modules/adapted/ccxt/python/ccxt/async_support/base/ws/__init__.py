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


# -*- coding: utf-8 -*-

from ccxt import (
    AccountSuspended,  # noqa: F401
    AddressPending,  # noqa: F401
    ArgumentsRequired,  # noqa: F401
    AuthenticationError,  # noqa: F401
    BadRequest,  # noqa: F401
    BadResponse,  # noqa: F401
    BaseError,  # noqa: F401
    CancelPending,  # noqa: F401
    DDoSProtection,  # noqa: F401
    DuplicateOrderId,  # noqa: F401
    ExchangeError,  # noqa: F401
    ExchangeNotAvailable,  # noqa: F401
    InsufficientFunds,  # noqa: F401
    InvalidAddress,  # noqa: F401
    InvalidNonce,  # noqa: F401
    InvalidOrder,  # noqa: F401
    NetworkError,  # noqa: F401
    NotSupported,  # noqa: F401
    NullResponse,  # noqa: F401
    OnMaintenance,  # noqa: F401
    OrderImmediatelyFillable,  # noqa: F401
    OrderNotCached,  # noqa: F401
    OrderNotFillable,  # noqa: F401
    OrderNotFound,  # noqa: F401
    PermissionDenied,  # noqa: F401
    RateLimitExceeded,  # noqa: F401
    RequestTimeout,  # noqa: F401
)

# -----------------------------------------------------------------------------
from ccxt.base import decimal_to_precision, errors

__all__ = decimal_to_precision.__all__ + errors.__all__  # noqa: F405
