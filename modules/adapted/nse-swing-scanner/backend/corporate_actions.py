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
corporate_actions.py
Pending corporate actions (next ~30 days).

Resolution chain:
  1. Probe NSE corporate-action JSON endpoints (best-effort).
  2. If unavailable, return 'source_failed' so the scanner can flag rather
     than silently pass.

The exact NSE API path changes; we try a few known candidates.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from cache import read_cache, write_cache
from nse_client import nse_get_json
from settings import CORPORATE_ACTION_LOOKAHEAD_DAYS, CORPORATE_ACTIONS_CACHE_TTL_SECONDS
from source_status import make_status

# Action types we treat as "excluded" — they create artificial price moves that
# contaminate the technical signal.
EXCLUDED_ACTION_TYPES = {
    "SPLIT",
    "BONUS",
    "RIGHTS",
    "DEEMERGER",
    "DEMERGER",
    "MERGER",
    "AMALGAMATION",
    "DELISTING",
    "SUSPENSION",
}

# Best-guess NSE endpoints; NSE has changed these before.
NSE_CA_CANDIDATES = [
    "/api/corporates-corporateActions",
    "/api/corporate-actions",
    "/api/equity-corporateActions",
]


def _probe_nse_corporate_actions(symbol: str, timeout: int = 10) -> dict | None:
    for path in NSE_CA_CANDIDATES:
        data = nse_get_json(path, timeout=timeout)
        if data is None:
            continue
        if isinstance(data, dict) and "data" in data:
            return data
        if isinstance(data, list):
            return {"_raw": data}
    return None


def _extract_actions_for_symbol(payload: dict, symbol: str) -> list[dict]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    sym_up = symbol.upper()
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or r.get("SYMBOL") or "").upper()
        if sym != sym_up:
            continue
        action = str(r.get("subject") or r.get("purpose") or r.get("action") or "").upper()
        ex_date = r.get("exDate") or r.get("ex_date") or r.get("recordDate") or r.get("record_date")
        out.append({"action": action, "ex_date": ex_date})
    return out


def _has_excluded_action_within(actions: list[dict], days: int) -> bool:
    cutoff = date.today() + timedelta(days=days)
    for a in actions:
        ex = a.get("ex_date")
        if not ex:
            continue
        try:
            d = datetime.fromisoformat(str(ex)[:10]).date()
        except Exception:
            continue
        # If the ex-date is within the next `days` days (or in the past few days,
        # a stock is still risky to enter on the technicals)
        if date.today() - timedelta(days=3) <= d <= cutoff:
            for excl in EXCLUDED_ACTION_TYPES:
                if excl in a.get("action", ""):
                    return True
    return False


def fetch_corporate_actions(symbol: str, *, lookahead_days: int = CORPORATE_ACTION_LOOKAHEAD_DAYS) -> dict:
    """
    Returns a source_status dict for one symbol.
    """
    cache_key = f"ca:{symbol.upper()}"
    cached = read_cache(cache_key, max_age_seconds=CORPORATE_ACTIONS_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    payload = _probe_nse_corporate_actions(symbol)
    if payload is None:
        result = make_status(
            source="nse:corporate-actions",
            status="source_failed",
            data={"has_excluded_action": None, "actions": []},
            error="NSE corporate-actions endpoint not reachable",
        )
        write_cache(cache_key, result)
        return result

    actions = _extract_actions_for_symbol(payload, symbol)
    has_excluded = _has_excluded_action_within(actions, lookahead_days)

    result = make_status(
        source="nse:corporate-actions",
        status="ok" if actions else "not_applicable",
        data={
            "has_excluded_action": has_excluded,
            "actions": actions,
        },
    )
    write_cache(cache_key, result)
    return result
