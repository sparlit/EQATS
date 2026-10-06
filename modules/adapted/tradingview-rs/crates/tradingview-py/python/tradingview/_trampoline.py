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
from collections.abc import Callable
from typing import Any


def callback_trampoline(cb: Callable[[Any], None], item: Any) -> None:
    """Invokes a callback with exception isolation via sys.unraisablehook."""
    try:
        cb(item)
    except Exception as exc:  # noqa: BLE001
        if hasattr(sys, "unraisablehook"):
            unraisable_args_cls = getattr(sys, "UnraisableHookArgs", None)
            if unraisable_args_cls is not None:
                sys.unraisablehook(
                    unraisable_args_cls(exc, "Exception in TradingView streaming callback", cb)
                )
            else:
                sys.unraisablehook(exc)  # type: ignore[arg-type]
