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


import threading

from fastapi import APIRouter, HTTPException

from app.core import db
from app.services.jobs import _event_scan_state, _run_event_scan

router = APIRouter(tags=["events"])


@router.post("/api/events/scan")
def trigger_event_scan(list_name: str | None = None):
    if _event_scan_state["running"]:
        raise HTTPException(status_code=409, detail="An event scan is already running")
    threading.Thread(target=_run_event_scan, args=(list_name,), daemon=True).start()
    return {"ok": True}


@router.get("/api/events/status")
def event_scan_status():
    return _event_scan_state


@router.get("/api/events")
def events_feed(
    list_name: str | None = None,
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
):
    return db.list_events(
        list_name=list_name, symbol=symbol, from_date=from_date, to_date=to_date, limit=limit
    )


@router.get("/api/events/attention")
def events_attention(
    list_name: str | None = None,
    symbol: str | None = None,
    baseline_days: int = 30,
    recent_days: int = 3,
):
    """Per-symbol event-coverage volume vs. that symbol's own baseline - see db.attention_scores.
    Powers the Events page's "Unusual attention" panel: which watchlisted stocks are getting more
    coverage than usual right now, not just what the latest single headline says."""
    return db.attention_scores(
        list_name=list_name, symbol=symbol, baseline_days=baseline_days, recent_days=recent_days
    )
