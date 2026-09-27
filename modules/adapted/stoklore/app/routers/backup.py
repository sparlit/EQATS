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


from fastapi import APIRouter, HTTPException

from app.core import backup

router = APIRouter(tags=["backup"])


@router.get("/api/backup/status")
def backup_status():
    return backup.status()


@router.post("/api/backup")
def backup_now():
    """Force a dump immediately - worth hitting before anything risky, rather than waiting out the
    interval."""
    try:
        return {"path": backup.run_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
