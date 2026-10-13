from __future__ import annotations

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


"""Best-effort process identity for source and packaged GUI launches."""


import logging
import sys

from app_metadata import PRODUCT_NAME


def configure_process_identity(name: str = PRODUCT_NAME) -> bool:
    """Expose the product name to process viewers during source launches.

    Nuitka supplies the native executable and bundle identity for packaged
    builds.  During development Python remains the executable, so setproctitle
    supplies a readable process name instead.  AppKit is optional and only
    updates the macOS process display name when PyObjC is already available.
    """

    configured = False
    try:
        import setproctitle

        setproctitle.setproctitle(name)
        configured = True
    except (ImportError, OSError, RuntimeError):
        logging.getLogger(__name__).debug(
            "setproctitle is unavailable; keeping the executable process name",
            exc_info=True,
        )

    if sys.platform == "darwin":
        try:
            from AppKit import NSProcessInfo  # type: ignore[import-untyped]

            NSProcessInfo.processInfo().setProcessName_(name)
            configured = True
        except (ImportError, AttributeError, OSError, RuntimeError):
            logging.getLogger(__name__).debug(
                "AppKit process naming is unavailable",
                exc_info=True,
            )
    return configured
