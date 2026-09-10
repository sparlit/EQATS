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


import sys

from pyalgo.core.context import Context
from pyalgo.core.engine import Engine
from pyalgo.core.trd import BarSubscription, DepthSubscription, SmartOrder

from .pyalgo import *


def info(msg: str):
    frame = sys._getframe(1)
    file = frame.f_code.co_filename
    lineno = frame.f_lineno
    pyalgo.log_info(file, lineno, msg)


def debug(msg: str):
    frame = sys._getframe(1)
    file = frame.f_code.co_filename
    lineno = frame.f_lineno
    pyalgo.log_debug(file, lineno, msg)


def warn(msg: str):
    frame = sys._getframe(1)
    file = frame.f_code.co_filename
    lineno = frame.f_lineno
    pyalgo.log_warn(file, lineno, msg)


def error(msg: str):
    frame = sys._getframe(1)
    file = frame.f_code.co_filename
    lineno = frame.f_lineno
    pyalgo.log_error(file, lineno, msg)


__all__ = [
    "BarSubscription",
    "Context",
    "DepthSubscription",
    "Engine",
    "SmartOrder",
    "debug",
    "error",
    "info",
    "warn",
]

__doc__ = pyalgo.__doc__
if hasattr(pyalgo, "__all__"):
    __all__.extend(pyalgo.__all__)
