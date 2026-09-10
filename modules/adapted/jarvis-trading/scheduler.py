from __future__ import annotations

import datetime
from datetime import date
from datetime import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytz

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    BackgroundScheduler = None
    BlockingScheduler = None
    CronTrigger = None

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

try:
    from ai.brain import generate_market_briefing, generate_task_list
    from data.fetcher import load_universe
    from data.market_context import build_briefing_context
    from monitors.intraday_monitor import make_monitor_from_watchlist
    from monitors.telegram_bot import send_briefing, send_document, send_message, send_regime_alert
    from reports.pdf_generator import generate_text_report
    from screener.regime_classifier import classify_regime
    from screener.screener import run_screener
except ImportError:
    pass

IST = ZoneInfo("Asia/Kolkata")
REPORTS_DIR = Path("data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

NSE_HOLIDAYS: dict[int, set[date]] = {
    2026: {
        date(2026, 1, 26),
        date(2026, 3, 25),
        date(2026, 4, 2),
        date(2026, 4, 10),
        date(2026, 4, 14),
        date(2026, 5, 1),
        date(2026, 8, 15),
        date(2026, 10, 2),
        date(2026, 11, 4),
        date(2026, 12, 25),
    },
}

NSE_HOLIDAYS_2026 = NSE_HOLIDAYS[2026]


def is_ist_market_session_active(dt: dt | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else dt.now(ist)
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


def is_market_day() -> bool:
    today = dt.now(IST).date()
    if today.weekday() >= 5:
        logger.info("Market closed — weekend")
        return False
    holidays = NSE_HOLIDAYS.get(today.year)
    if holidays is None:
        logger.warning("No NSE holiday calendar for %s — assuming trading day", today.year)
        return True
    if today in holidays:
        logger.info("Market closed — holiday: %s", today)
        return False
    return True
