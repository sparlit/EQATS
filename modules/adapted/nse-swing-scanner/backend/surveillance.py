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
surveillance.py
T-group / GSM / suspension exclusion list.

Resolution chain (per the publish plan):
  1. NSE — probe a handful of likely internal JSON endpoints behind the
     securities-available-for-trading SPA. If any returns a usable list, use it.
  2. BSE — fall back to BSE's equivalent surveillance/security list.
  3. Flag-only — if both fail, return a source_status of "flag_only" and let
     the scanner treat the result as "no information", not as a clean pass.

NOTE: The old `eq_securititeis.csv` path that the previous backend/README
documented was verified 404 at plan time. The list is now served via the NSE
SPA, so we probe a few known internal JSON shapes. If they all 404, the BSE
fallback kicks in.
"""

import io
import json
import re
import time
from typing import Dict, List, Optional

import requests
from cache import DEFAULT_CACHE_DIR, read_cache, write_cache
from nse_client import NSE_ARCHIVES_BASE, NSE_BASE, nse_get, nse_get_json
from settings import SURVEILLANCE_CACHE_TTL_SECONDS
from source_status import make_status, worst_status

# --- NSE endpoint candidates (probed in order) ---
# These are best-guess internal endpoints behind the SPA at
# /market-data/securities-available-for-trading and
# /market-data/price-bands-surveillance-actions. NSE has changed these before;
# none of them are part of a documented public API, so we probe and degrade
# gracefully.
NSE_SURVEILLANCE_CANDIDATES = [
    "/api/surveillance/securities-available-for-trading",
    "/api/surveillance/asm-list",
    "/api/surveillance/gsm-list",
    "/api/equity-stockIndices?index=SECURITIES_IN_FOCUS",
]

# --- BSE fallback ---
BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/csv,text/html,application/json,*/*",
    "Referer": "https://www.bseindia.com/",
}


def _probe_nse_surveillance(timeout: int = 10) -> dict | None:
    for path in NSE_SURVEILLANCE_CANDIDATES:
        resp = nse_get(path, timeout=timeout)
        if resp is None:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if isinstance(data, (list, dict)) and data:
            return {"_endpoint": path, "_payload": data}
    return None


def _probe_bse_surveillance(timeout: int = 10) -> dict | None:
    """
    BSE publishes surveillance/security-watch data. The exact endpoint path has
    changed in the past; the public pages also render dynamically. We try a
    handful of candidates and only return a payload if the response body looks
    like actual surveillance data (contains one of the expected markers).
    """
    candidates = [
        "https://www.bseindia.com/markets/equity/EQReports/SecurityWatch_Surv.aspx?type=ASM",
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCatData/w?subcat=ASM",
    ]
    markers = ("ASM", "GSM", "T1T", "T2T", "SURVEILLANCE", "surveillance")
    for url in candidates:
        try:
            r = requests.get(url, headers=BSE_HEADERS, timeout=timeout)
        except Exception:
            continue
        if r.status_code != 200 or len(r.text) < 200:
            continue
        # Refuse generic pages (e.g. BSE homepage) — those would produce garbage
        # matches when we extract codes.
        body = r.text
        if not any(m.lower() in body.lower() for m in markers):
            continue
        return {"_endpoint": url, "_payload": body}
    return None


def _extract_nse_restricted(payload: dict) -> list[str]:
    """Best-effort extraction of restricted symbol list from a NSE JSON payload."""
    symbols: list[str] = []
    data = payload.get("_payload")
    if isinstance(data, dict):
        for key in ("data", "symbols", "records", "result"):
            v = data.get(key)
            if isinstance(v, list):
                data = v
                break
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                sym = item.get("symbol") or item.get("SYMBOL") or item.get("Symbol")
                if sym:
                    symbols.append(str(sym).upper())
            elif isinstance(item, str):
                symbols.append(item.upper())
    return list(set(symbols))


def _extract_bse_restricted(payload: dict) -> list[str]:
    """Best-effort extraction from a BSE HTML/CSV payload. Looks for BSE scrip
    codes in the response and maps them to a best-effort symbol list. This is
    not perfect (BSE codes ≠ NSE symbols), so callers should use the returned
    status conservatively.

    To avoid garbage matches from generic BSE pages (which mention 6-digit
    numbers in nav, CSS, etc.), we require the body to actually look like a
    surveillance table — at least 5 distinct 6-digit codes — before returning
    any. Otherwise the caller will get an empty list and we degrade to flag_only.
    """
    text = payload.get("_payload", "")
    codes = re.findall(r"\b\d{6}\b", text)
    distinct = list(set(codes))
    if len(distinct) < 5:
        return []
    return distinct


def fetch_surveillance_list(timeout: int = 10) -> dict:
    """
    Returns a source_status dict with:
      - status: 'ok' | 'fallback_used' | 'source_failed' | 'flag_only'
      - data: dict mapping symbol -> {'t_group': bool, 'gsm': bool, 'suspended': bool, 'source': str}
    """
    cache_key = "surveillance:list"
    cached = read_cache(cache_key, max_age_seconds=SURVEILLANCE_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    nse = _probe_nse_surveillance(timeout=timeout)
    if nse is not None:
        symbols = _extract_nse_restricted(nse)
        per_symbol = {
            s: {"t_group": True, "gsm": False, "suspended": False, "source": nse["_endpoint"]} for s in symbols
        }
        result = make_status(
            source=f"nse:{nse['_endpoint']}",
            status="ok",
            data=per_symbol,
        )
        write_cache(cache_key, result)
        return result

    bse = _probe_bse_surveillance(timeout=timeout)
    if bse is not None:
        codes = _extract_bse_restricted(bse)
        if not codes:
            result = make_status(
                source=f"bse:{bse['_endpoint']}",
                status="flag_only",
                data={},
                error="BSE response did not contain enough surveillance markers",
            )
            write_cache(cache_key, result)
            return result
        per_symbol = {
            c: {"t_group": True, "gsm": False, "suspended": False, "source": "bse_surveillance"} for c in codes
        }
        result = make_status(
            source=f"bse:{bse['_endpoint']}",
            status="fallback_used",
            data=per_symbol,
            error="BSE codes mapped, cross-check required for NSE symbols",
        )
        write_cache(cache_key, result)
        return result

    result = make_status(
        source="none",
        status="flag_only",
        data={},
        error="Neither NSE nor BSE surveillance list was reachable",
    )
    write_cache(cache_key, result)
    return result


def check_symbol(surveillance_payload: dict, symbol: str) -> dict:
    """
    Look up a single symbol in a surveillance source_status payload.
    Returns a status dict for that symbol.
    """
    overall = surveillance_payload.get("status", "flag_only")
    per = surveillance_payload.get("data") or {}
    hit = per.get(symbol.upper())
    if hit is not None:
        return {
            "is_restricted": bool(hit.get("t_group") or hit.get("gsm") or hit.get("suspended")),
            "restriction_type": "t_group"
            if hit.get("t_group")
            else "gsm"
            if hit.get("gsm")
            else "suspended"
            if hit.get("suspended")
            else None,
            "source_status": overall,
            "source": hit.get("source", surveillance_payload.get("source")),
        }
    return {
        "is_restricted": False,
        "restriction_type": None,
        "source_status": overall,
        "source": surveillance_payload.get("source"),
    }
