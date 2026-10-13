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
Supabase writer for the live options scan.

The collector (VM) upserts the whole enriched scan each cycle into one table
(`options_scan`), keyed by token — so the table always holds the latest snapshot
(~2,500 rows), which the Streamlit app reads. Mirrors the alerter's Supabase auth
(SUPABASE_URL + SUPABASE_SERVICE_KEY from env).
"""
import os

_client = None
CHUNK = 500


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client

        url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
        if not (url and key):
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        _client = create_client(url, key)
    return _client


def upsert_scan(rows):
    """Upsert enriched contract rows (list of dicts) keyed on token."""
    cli = _get_client()
    n = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        cli.table("options_scan").upsert(chunk, on_conflict="token").execute()
        n += len(chunk)
    return n


def prune_stale(before_iso):
    """Remove rows older than a cutoff (contracts that dropped out of scope,
    e.g. after an expiry roll) so the table doesn't accumulate dead tokens."""
    _get_client().table("options_scan").delete().lt("as_of", before_iso).execute()
