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


"""
nse_client.py
Centralized HTTP client for NSE endpoints.

NSE returns 401/403 without browser-like headers and an established cookie. This
module handles cookie priming and a shared session so callers don't all duplicate
the dance.

NSE has changed archive paths before without notice. If a probe returns 404 or
HTML rather than JSON/CSV, callers should fall back to a documented secondary
source and report `fallback_used` source-status, not fail silently.
"""

import contextlib
from typing import Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
}

NSE_BASE = "https://www.nseindia.com"
NSE_ARCHIVES_BASE = "https://nsearchives.nseindia.com"

_session: requests.Session | None = None


def get_session() -> requests.Session:
    """Return a shared requests.Session primed with NSE cookies."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(DEFAULT_HEADERS)
        # Prime cookies by hitting the homepage once. Cheap; needed for several
        # NSE JSON endpoints which 401 without an established session cookie.
        with contextlib.suppress(Exception):
            s.get(NSE_BASE + "/", timeout=10)
        _session = s
    return _session


def nse_get(
    path: str, *, base: str = NSE_BASE, timeout: int = 10, params: dict | None = None
) -> requests.Response | None:
    """GET against NSE; returns the Response on 2xx, else None."""
    s = get_session()
    try:
        resp = s.get(base + path, params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp
    except Exception:
        return None
    return None


def nse_get_json(path: str, **kwargs) -> dict | None:
    resp = nse_get(path, **kwargs)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None
