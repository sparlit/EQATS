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


"""Shared NSE HTTP client. NSE blocks obvious bots: send browser headers,
warm up cookies against the homepage before hitting /api/, retry on 401/403."""
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        try:  # cookie warmup, needed for www.nseindia.com/api/* endpoints
            s.get("https://www.nseindia.com", timeout=15)
        except requests.RequestException:
            pass
        _session = s
    return _session


def get(url: str, timeout: int = 30, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            r = session().get(url, timeout=timeout)
            if r.status_code in (401, 403):
                # cookie expired / bot-flagged: rebuild session, back off
                globals()["_session"] = None
                time.sleep(3 * (attempt + 1))
                continue
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    return r
