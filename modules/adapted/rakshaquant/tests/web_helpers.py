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


"""Shared fixtures for the web tests: a fixed launch token and an authenticated client."""


from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.web.security import WebSecurity

TOKEN = "test-token-0123456789abcdefghijklmnopqrstuv"
BASE = "http://127.0.0.1:8000"
ORIGIN = BASE
WS_URL = "ws://127.0.0.1:8000/ws"  # websocket_connect ignores base_url
SECURITY = WebSecurity.for_launch("127.0.0.1", 8000, token=TOKEN)
PROTOCOLS = ["rq.v1", f"rq.token.{TOKEN}"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def authed(app: FastAPI) -> TestClient:
    """A client on the console's own host, sending the token (as the SPA does)."""
    return TestClient(app, base_url=BASE, headers=AUTH)


def anonymous(app: FastAPI) -> TestClient:
    return TestClient(app, base_url=BASE)
