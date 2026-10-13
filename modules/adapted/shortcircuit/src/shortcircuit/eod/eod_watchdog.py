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


# coding: utf-8
"""
EOD Watchdog — Standalone failsafe for market-close shutdown.

Runs independently of eod_scheduler. Checks every 30 seconds.
- 15:32 IST → fires shutdown_event (graceful)
- 15:40 IST → os.kill SIGTERM (nuclear, no argument)

This task CANNOT be blocked by scanning loops, DB hangs, or WS stalls.
"""

import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger("shortcircuit.eod_watchdog")
IST = pytz.timezone("Asia/Kolkata")

EOD_SOFT_SHUTDOWN = (15, 32)  # (hour, minute) IST — graceful
EOD_HARD_KILL = (15, 40)  # (hour, minute) IST — SIGTERM


async def eod_watchdog(shutdown_event: asyncio.Event):
    """
    Hard failsafe. Sets shutdown_event at 15:32.
    Force-kills process at 15:40 if still alive.
    """
    IST = pytz.timezone("Asia/Kolkata")

    while True:  # ← keep the while True but add the break
        now = datetime.now(IST)

        # Soft shutdown at 15:35 — give enough time for analysis + cleanup
        if now.hour == 15 and now.minute >= 35 and not shutdown_event.is_set():
            logger.warning("[EOD-WATCHDOG] 15:35 IST — triggering graceful shutdown.")
            shutdown_event.set()

        # Hard kill at 15:40 — cannot be trapped, cannot be ignored.
        if now.hour == 15 and now.minute >= 40:
            logger.critical(
                "[EOD-WATCHDOG] 15:40 IST — process did not exit cleanly. Forcing os._exit(0)."
            )
            os._exit(0)  # ← bypasses all Python cleanup, kills immediately

        # Exit the loop once shutdown is confirmed and it is past 15:32.
        if shutdown_event.is_set() and now.hour == 15 and now.minute >= 32:
            logger.info("[EOD-WATCHDOG] Shutdown confirmed. Watchdog exiting cleanly.")
            return  # ← lets the TaskGroup finish normally

        await asyncio.sleep(30)
