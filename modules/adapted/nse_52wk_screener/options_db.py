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


"""
Read side of the live options-flow scan (the `options_scan` table the VM collector
upserts every ~2 min). Same Supabase creds as the price alerts (st.secrets on
Cloud, env locally). Degrades gracefully when Supabase isn't configured.
"""

import os

try:
    from supabase import create_client

    _HAS_SUPABASE = True
except Exception:
    _HAS_SUPABASE = False

_client = None
_PAGE = 1000


def _cred(name: str) -> str | None:
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


def configured() -> bool:
    return _HAS_SUPABASE and bool(_cred("SUPABASE_URL")) and bool(_cred("SUPABASE_SERVICE_KEY"))


def _get_client():
    global _client
    if _client is None:
        url, key = _cred("SUPABASE_URL"), _cred("SUPABASE_SERVICE_KEY")
        if not (_HAS_SUPABASE and url and key):
            raise RuntimeError("Supabase is not configured.")
        _client = create_client(url, key)
    return _client


def load_scan():
    """All rows of options_scan as a DataFrame (paginated past PostgREST's 1000
    row cap). Empty df if unconfigured/empty."""
    import pandas as pd

    if not configured():
        return pd.DataFrame()
    cli = _get_client()
    rows, start = [], 0
    while True:
        r = cli.table("options_scan").select("*").range(start, start + _PAGE - 1).execute()
        d = r.data or []
        rows.extend(d)
        if len(d) < _PAGE:
            break
        start += _PAGE
    return pd.DataFrame(rows)
