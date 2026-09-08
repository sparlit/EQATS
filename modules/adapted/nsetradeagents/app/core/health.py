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


"""Liveness state for the /health endpoint.

Lives outside the API layer so the scan can report in without importing
FastAPI — main.py drives the pipeline and should not depend on the web app.
"""

from datetime import datetime

import structlog
from app.core.database import get_db
from app.models.models import ScanRun
from sqlalchemy import desc

logger = structlog.get_logger()

# Long enough to survive a weekend plus a Monday holiday.
MAX_SCAN_AGE_HOURS = 96

_last_scan: datetime | None = None
_loaded = False


def note_scan_run(at: datetime) -> None:
    """Record in memory that a scan just finished."""
    global _last_scan, _loaded
    _last_scan = at
    _loaded = True


def last_scan_at() -> datetime | None:
    """When the last scan ran, hitting the database only on a cold process.

    An external monitor polls /health constantly. A query per poll would keep
    hosted Postgres permanently awake, so the answer is cached after the first
    read and refreshed by note_scan_run.
    """
    global _last_scan, _loaded
    if not _loaded:
        try:
            with get_db() as db:
                row = db.query(ScanRun).order_by(desc(ScanRun.ran_at)).first()
                # Read inside the block: get_db commits on exit, which expires
                # the instance, and touching it afterwards raises
                # DetachedInstanceError.
                _last_scan = row.ran_at if row else None
            _loaded = True
        except Exception as e:
            # A health endpoint that 500s is useless in exactly the situation
            # it exists to report on. Stay unloaded so the next call retries.
            logger.exception("health_read_failed", error=str(e))
            return None
    return _last_scan
