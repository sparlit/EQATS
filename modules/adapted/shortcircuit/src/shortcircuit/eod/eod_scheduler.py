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
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from datetime import time as dt_time

IST = pytz.timezone("Asia/Kolkata")
EOD_TIME = dt_time(15, 10, 0)
EOD_ANALYSIS_TIME = dt_time(15, 32, 0)

logger = logging.getLogger("shortcircuit.eod_scheduler")


def _get_now() -> datetime:
    return datetime.now(IST)


async def eod_scheduler(
    shutdown_event: asyncio.Event,
    trigger_eod_squareoff: Callable[[], Awaitable[None]],
    run_eod_analysis: Callable[[], Awaitable[None]],
    notify: Callable[[str], Awaitable[None]],
    get_open_positions: Callable[[], Awaitable[list]],
    bot_start_time: datetime,
    _now_fn: Callable[[], datetime] = _get_now,
) -> None:
    """
    Independent EOD task, decoupled from the trading scanner lifecycle.
    """
    eod_done_today = False
    analysis_done_today = False
    last_date = None

    while not shutdown_event.is_set():
        now = _now_fn()
        today = now.date()

        if last_date != today:
            eod_done_today = False
            analysis_done_today = False
            last_date = today

        if not eod_done_today and now.time() >= EOD_TIME:
            # Guard against late starts: only fire if we had open positions
            # or process started before 15:10 IST.
            should_fire = False
            try:
                open_positions = await get_open_positions()
                should_fire = bool(open_positions) or bot_start_time.time() < EOD_TIME
            except Exception as exc:
                logger.error("[EOD_SCHEDULER] Failed to fetch open positions: %s", exc)
                should_fire = bot_start_time.time() < EOD_TIME

            if should_fire:
                logger.info("[EOD_SCHEDULER] 15:10 reached; triggering forced square-off.")
                try:
                    # Only announce success when the caller could actually PROVE the
                    # account is flat. Previously this always reported "complete",
                    # even one second after a timeout warning.
                    ok = await trigger_eod_squareoff()
                    if ok is False:
                        logger.error(
                            "[EOD_SCHEDULER] Square-off did not verify flat — "
                            "operator has been alerted."
                        )
                    else:
                        await notify("EOD Square-off complete.")
                except Exception as exc:
                    logger.error("[EOD_SCHEDULER] Square-off failed: %s", exc)
                    await notify(f"EOD Square-off FAILED: {exc}")
            else:
                logger.info("[EOD_SCHEDULER] No positions + late start; skipping square-off.")

            # Always latch, even when skipped, to prevent double fire.
            eod_done_today = True

        if not analysis_done_today and now.time() >= EOD_ANALYSIS_TIME:
            logger.info("[EOD_SCHEDULER] 15:32 reached; triggering EOD analysis.")
            try:
                await run_eod_analysis()
            except Exception as exc:
                logger.error("[EOD_SCHEDULER] Analysis failed: %s", exc)
                await notify(f"EOD Analysis FAILED: {exc}")
            analysis_done_today = True

            # Fire graceful shutdown after EOD work is done
            logger.info("[EOD_SCHEDULER] All EOD tasks complete. Firing shutdown.")
            await notify("✅ EOD complete. Shutting down bot.")
            shutdown_event.set()
            return  # Exit scheduler — shutdown_event will stop all other tasks

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=15)
        except TimeoutError:
            continue
