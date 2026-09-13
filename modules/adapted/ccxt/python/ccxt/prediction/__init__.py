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

"""CCXT Prediction: prediction-market exchanges (async)"""

# ----------------------------------------------------------------------------

__version__ = "4.5.78"

# ----------------------------------------------------------------------------

from ccxt.async_support.base.exchange import Exchange
from ccxt.base import errors

# DO_NOT_REMOVE__ERROR_IMPORTS_START
from ccxt.base.errors import (
    AccountNotEnabled,
    AccountSuspended,
    AddressPending,
    ArgumentsRequired,
    AuthenticationError,
    BadRequest,
    BadResponse,
    BadSymbol,
    BaseError,
    CancelPending,
    ChecksumError,
    ContractUnavailable,
    DDoSProtection,
    DuplicateOrderId,
    ExchangeClosedByUser,
    ExchangeError,
    ExchangeNotAvailable,
    InsufficientFunds,
    InvalidAddress,
    InvalidNonce,
    InvalidOrder,
    InvalidProxySettings,
    ManualInteractionNeeded,
    MarginModeAlreadySet,
    MarketClosed,
    NetworkError,
    NoChange,
    NotSupported,
    NullResponse,
    OnMaintenance,
    OperationFailed,
    OperationRejected,
    OrderImmediatelyFillable,
    OrderNotCached,
    OrderNotFillable,
    OrderNotFound,
    PermissionDenied,
    RateLimitExceeded,
    RequestTimeout,
    RestrictedLocation,
    UnsubscribeError,
    error_hierarchy,
)
from ccxt.base.precise import Precise

# DO_NOT_REMOVE__ERROR_IMPORTS_END
from ccxt.prediction.binance import binance
from ccxt.prediction.hyperliquid import hyperliquid
from ccxt.prediction.kalshi import kalshi
from ccxt.prediction.limitless import limitless
from ccxt.prediction.myriad import myriad
from ccxt.prediction.opinion import opinion
from ccxt.prediction.polymarket import polymarket

exchanges = [
    "binance",
    "hyperliquid",
    "kalshi",
    "limitless",
    "myriad",
    "opinion",
    "polymarket",
]
