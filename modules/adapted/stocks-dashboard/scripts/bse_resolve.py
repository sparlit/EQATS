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


# -*- coding: utf-8 -*-
"""ISIN-GUARDED NSE-symbol -> BSE-scrip resolution.  (2026-08-10, after the KALYANI trap; §76)

★ THE RULE: a BSE `scrip_id` that equals our NSE ticker is a COINCIDENCE TO BE DISPROVED, never
a match to be trusted. Gate on ISIN — the only identifier both exchanges agree on.

WHY THIS EXISTS. `bse_scrips.json` "by_id" is BSE's `scrip_id` -> `SCRIP_CD`, but every consumer in
this repo uses it as "NSE symbol -> BSE scrip code". Those are different namespaces that happen to
collide. KALYANI is the 4th instance of the class (after TRU/CCL/SHK, §72):

    our KALYANI = Kalyani Commercials Ltd  INE610E01010  (NSE-only, NOT listed on BSE at all)
    by_id[KALYANI] -> 544023 = Kalyani Cast-Tech Ltd  INE0N6U01018  (a different company)

Three of its quarters were filled with Cast-Tech's profits, its con slots invented from Cast-Tech's
consolidated filings, and one announce date taken from Cast-Tech's calendar, before the std-PAT
adjudication (§73) caught it. A full scan of the 2,225 checkable symbols found exactly TWO live
conflicts — KALYANI and FOCUS — both recorded in `bse_scrip_isin_conflicts.json`.

Note the asymmetry that makes this dangerous: a WRONG code fails no magnitude check, no anchor, no
identity guard that only reads the document the wrong code pointed at. The document is internally
perfect; it just belongs to somebody else. Only ISIN catches it.

USE:
    import bse_resolve
    by_id = bse_resolve.by_id()          # bse_scrips by_id with conflicting symbols REMOVED
    code  = bse_resolve.guard(sym, code) # -> code, or None when sym is a known conflict
    bse_resolve.guard_map(m)             # filter any {SYM: code} map in place-safe fashion

Refresh the conflict list with:  python3 scripts/scan_scrip_isin_conflicts.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFLICTS_PATH = os.path.join(HERE, "bse_scrip_isin_conflicts.json")
SCRIPS_PATH = os.path.join(HERE, "bse_scrips.json")

_cache = None


def conflicts():
    """{SYMBOL: {nse_isin, bse_code, bse_isin, bse_name, note}} — symbols whose by_id/scrip_id
    match points at a DIFFERENT company. Missing/unreadable file -> {} (never crash a caller);
    the guard then degrades to a no-op, which is the pre-2026-08-10 behaviour."""
    global _cache
    if _cache is None:
        try:
            d = json.load(open(CONFLICTS_PATH, encoding="utf-8"))
            _cache = {k.upper(): v for k, v in (d.get("conflicts") or {}).items()}
        except Exception:
            _cache = {}
    return _cache


def blocked(sym):
    """Reason string when `sym` must NOT be resolved to a BSE scrip, else None."""
    e = conflicts().get(str(sym).upper())
    if not e:
        return None
    return "{} -> BSE {} is {} (ISIN {}), but {} is ISIN {}".format(
        sym, e.get("bse_code"), e.get("bse_name"), e.get("bse_isin"), sym, e.get("nse_isin")
    )


def guard(sym, code):
    """Return `code` unless `sym` is a known wrong-company mapping, in which case None."""
    return None if (code is not None and blocked(sym)) else code


def guard_map(m):
    """Copy of a {SYM: code} map with every known-conflicting symbol dropped."""
    bad = conflicts()
    return {k: v for k, v in m.items() if str(k).upper() not in bad}


def by_id(path=None):
    """bse_scrips.json['by_id'], ISIN-guarded. This is the call every fundamentals-feeding
    consumer should use instead of json.load(...)['by_id']."""
    d = json.load(open(path or SCRIPS_PATH, encoding="utf-8"))
    return guard_map(d.get("by_id") or {})


def by_isin(path=None):
    """bse_scrips.json['by_isin'] — ISIN -> scrip code. Always safe: ISIN is unambiguous."""
    d = json.load(open(path or SCRIPS_PATH, encoding="utf-8"))
    return dict(d.get("by_isin") or {})


if __name__ == "__main__":
    c = conflicts()
    print("known scrip_id/ISIN conflicts: %d" % len(c))
    for k in sorted(c):
        print(f"  {blocked(k)}")
    raw = json.load(open(SCRIPS_PATH, encoding="utf-8")).get("by_id") or {}
    print("by_id raw=%d  guarded=%d" % (len(raw), len(by_id())))
