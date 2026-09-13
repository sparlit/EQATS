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


"""Supabase access for the price-alert features in the screener.

Self-contained on purpose: the screener deploys separately (Streamlit Cloud)
from the alerter (GCP VM), so it carries its own copy of the DB layer rather
than importing the alerter's. Mirrors stock_price_alerter/db.py.

Config is read from st.secrets first (Streamlit Cloud), then environment vars
(local dev). Degrades gracefully — if Supabase isn't configured or the package
isn't installed, configured() returns False and the UI shows a hint instead of
crashing the screener.
"""

import os
from typing import Any

try:
    from supabase import create_client

    _HAS_SUPABASE = True
except Exception:  # package not installed yet
    _HAS_SUPABASE = False

_client = None


def _cred(name: str) -> str | None:
    """st.secrets first (Cloud), then env var (local dev)."""
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


def configured() -> bool:
    """True only if the package is present and both creds are set."""
    return _HAS_SUPABASE and bool(_cred("SUPABASE_URL")) and bool(_cred("SUPABASE_SERVICE_KEY"))


def _get_client():
    global _client
    if _client is None:
        url, key = _cred("SUPABASE_URL"), _cred("SUPABASE_SERVICE_KEY")
        if not (_HAS_SUPABASE and url and key):
            msg = "Supabase is not configured."
            raise RuntimeError(msg)
        _client = create_client(url, key)
    return _client


def add_alert(
    symbol: str,
    *,
    upper: float | None = None,
    lower: float | None = None,
    exchange: str = "NSE",
    note: str | None = None,
) -> dict[str, Any]:
    if upper is None and lower is None:
        msg = "Provide at least one of upper / lower."
        raise ValueError(msg)
    row = {
        "symbol": symbol.strip().upper(),
        "exchange": exchange,
        "upper_price": upper,
        "lower_price": lower,
        "note": note,
    }
    return _get_client().table("alerts").insert(row).execute().data[0]


def list_alerts(active_only: bool = False) -> list[dict[str, Any]]:
    q = _get_client().table("alerts").select("*").order("created_at", desc=True)
    if active_only:
        q = q.eq("active", True)
    return q.execute().data


def set_active(alert_id: int, active: bool) -> None:
    _get_client().table("alerts").update({"active": active}).eq("id", alert_id).execute()


def rearm(alert_id: int) -> None:
    """Re-activate an alert and clear its trigger stamp, so it watches again.
    Used to resume a paused alert or re-arm one that already fired (one-shot)."""
    _get_client().table("alerts").update({"active": True, "last_alert_at": None}).eq("id", alert_id).execute()


def delete_alert(alert_id: int) -> None:
    _get_client().table("alerts").delete().eq("id", alert_id).execute()
