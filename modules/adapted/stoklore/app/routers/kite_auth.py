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


import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.core import db, kite

router = APIRouter(tags=["kite-auth"])


@router.get("/api/kite/login-url")
def kite_login_url():
    creds = db.get_kite_credentials()
    if not creds:
        raise HTTPException(
            status_code=400,
            detail="Kite isn't configured - add your API key and secret in Settings > Kite",
        )
    return {"url": kite.login_url(creds["api_key"])}


# The frontend runs on its own dev-server origin (run.sh's fixed port 5180), separate from this
# API's - a relative RedirectResponse below would redirect within this API's own origin instead.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5180")


@router.get("/api/kite/callback")
def kite_callback(request_token: str | None = None, status: str | None = None):
    """Where Kite's login redirect lands (register this exact URL - http://localhost:8010/api/kite/callback
    - as the app's Redirect URL at developers.kite.trade/apps). Exchanges request_token for a
    day-valid access_token server-side, then bounces the browser back into the app."""
    creds = db.get_kite_credentials()
    if not creds:
        raise HTTPException(status_code=400, detail="Kite isn't configured")
    if status != "success" or not request_token:
        return RedirectResponse(f"{FRONTEND_URL}/holdings?broker=kite&kite_login=failed")
    try:
        access_token = kite.generate_session(creds["api_key"], creds["api_secret"], request_token)
    except kite.KiteError:
        return RedirectResponse(f"{FRONTEND_URL}/holdings?broker=kite&kite_login=failed")
    db.set_kite_session(access_token)
    return RedirectResponse(f"{FRONTEND_URL}/holdings?broker=kite&kite_login=success")
