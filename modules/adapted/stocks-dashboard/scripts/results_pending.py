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
"""Single source of truth for "which declared results still have no numbers".

Pure JSON — no fitz/network imports — so it is safe to run in a light CI step.
Both consumers read from here so their counts can never drift:
  - bse_vision_prep.py     (the scheduled vision routine's prep — renders the pending)
  - build_results_coverage.py (the Results coverage dashboard — counts them)

classify() walks results_feed.json for the current quarter and buckets every declared
company. Status values:
  filled   — we have numbers for the quarter (XBRL/OCR cron, or an earlier vision fill)
  pending  — declared, no numbers, and an attachment exists → the routine will fill it
  no_pdf   — declared, no numbers, but the filing carries NO attachment to render.
             The routine CANNOT fill these; they need the XBRL cron to post.
  bse_dup  — NSE-side row flagged as also-BSE-listed; handled by the BSE pipeline, not here.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "docs")


def _load(name, default=None):
    p = os.path.join(D, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def rows_of(qs):
    return qs if isinstance(qs, list) else list(qs.values())


def classify():
    """Return (qe, rows) where rows = [{sym,name,exch,scrip,mcap,status,ann,pdf}] for every
    company that declared a result for the current quarter."""
    qr = _load("quarterly_results.json") or {}
    qe = qr["quarters"][0]
    CO = qr["co"]
    feed = (_load("results_feed.json") or {"rows": []})["rows"]
    univ = {r[1].upper(): r for r in (_load("bse_universe.json") or {"rows": []})["rows"]}
    bf = (_load("bse_fundamentals.json") or {}).get("px", {})
    sf = _load("sf_fundamentals.json") or {}
    vf = _load("vision_fills.json") or {}

    # NSE symbols whose quarter row already carries a revenue or profit figure
    nse_have = {
        s
        for s, qs in sf.items()
        if any(
            isinstance(r, list) and r and int(r[0]) == qe and (r[1] is not None or (len(r) > 3 and r[3] is not None))
            for r in rows_of(qs)
        )
    }

    seen, out = {}, []
    for r in feed:
        if r[3] != qe:
            continue
        sym = r[0].upper()
        ann, pdf = r[2][:10], (r[5] or "")
        if sym in seen:  # keep the latest filing per symbol
            e = seen[sym]
            if ann >= e["ann"]:
                e["ann"], e["pdf"] = ann, pdf or e["pdf"]
            continue

        if sym in univ:  # BSE-only name
            u = univ[sym]
            scrip = str(u[0])
            filled = scrip in bf and str(qe) in bf[scrip]
            e = {
                "sym": sym,
                "name": u[2],
                "exch": "BSE",
                "scrip": scrip,
                "mcap": u[6] or 0,
                "status": "filled" if filled else "pending",
                "ann": ann,
                "pdf": pdf,
            }
        elif sym in CO and not CO[sym].get("bse"):  # NSE name with a price-universe row
            filled = sym in nse_have or (sym in vf and str(qe) in vf.get(sym, {}))
            e = {
                "sym": sym,
                "name": CO[sym]["n"],
                "exch": "NSE",
                "scrip": "",
                "mcap": CO[sym].get("m") or 0,
                "status": "filled" if filled else "pending",
                "ann": ann,
                "pdf": pdf,
            }
        elif sym not in CO:  # orphan NSE (no price row, not BSE-listed)
            filled = sym in vf and str(qe) in vf.get(sym, {})
            e = {
                "sym": sym,
                "name": r[1],
                "exch": "NSE",
                "scrip": "",
                "mcap": 0,
                "status": "filled" if filled else "pending",
                "ann": ann,
                "pdf": pdf,
            }
        else:  # NSE row flagged also-BSE-listed
            e = {
                "sym": sym,
                "name": CO[sym]["n"],
                "exch": "NSE",
                "scrip": "",
                "mcap": CO[sym].get("m") or 0,
                "status": "bse_dup",
                "ann": ann,
                "pdf": pdf,
            }

        # BSE-only names are fetched by scrip (attachment looked up live), so a missing feed
        # filename does not block them; NSE names are fetched from the feed's own PDF path.
        if e["status"] == "pending" and e["exch"] == "NSE" and not e["pdf"]:
            e["status"] = "no_pdf"
        seen[sym] = e
        out.append(e)

    # qe==0 rows: the filing's stated period couldn't be parsed (headline had no "ended <date>"
    # clause). Before 2026-07-21 these were counted NOWHERE — not pending, not declared, invisible
    # to the vision routine AND to tl_reconcile's heal (YESBANK sat unclassified for 3 days).
    # Emit them as status "unknown_qe" so the coverage page shows them and bse_vision_prep can
    # resolve the real quarter from the filing PDF (feed_qe_fix.json re-files the row).
    for r in feed:
        if r[3] != 0:
            continue
        sym = r[0].upper()
        if sym in seen:
            continue
        ann, pdf = r[2][:10], (r[5] or "")
        if sym in univ:
            u = univ[sym]
            e = {
                "sym": sym,
                "name": u[2],
                "exch": "BSE",
                "scrip": str(u[0]),
                "mcap": u[6] or 0,
                "status": "unknown_qe",
                "ann": ann,
                "pdf": pdf,
            }
        else:
            c = CO.get(sym)
            e = {
                "sym": sym,
                "name": (c["n"] if c else r[1]),
                "exch": "NSE",
                "scrip": "",
                "mcap": (c.get("m") if c else 0) or 0,
                "status": "unknown_qe",
                "ann": ann,
                "pdf": pdf,
            }
        seen[sym] = e
        out.append(e)
    return qe, out


def find_unknown_qe(limit=12):
    """qe==0 feed rows for bse_vision_prep's quarter-resolution pass — biggest-mcap first."""
    _, rows = classify()
    un = [(e["sym"], e["name"], e["mcap"], e["pdf"], e["ann"], e["scrip"]) for e in rows if e["status"] == "unknown_qe"]
    un.sort(key=lambda x: -(x[2] or 0))
    return un[:limit]


def find_pending(limit):
    """(qe, nse, bse) in the shape bse_vision_prep expects — biggest-mcap first."""
    qe, rows = classify()
    nse = [
        (e["sym"], e["name"], e["mcap"], e["pdf"], e["ann"])
        for e in rows
        if e["status"] == "pending" and e["exch"] == "NSE"
    ]
    bse = [
        (e["scrip"], (e["sym"], e["name"], e["mcap"])) for e in rows if e["status"] == "pending" and e["exch"] == "BSE"
    ]
    nse.sort(key=lambda x: -(x[2] or 0))
    bse.sort(key=lambda kv: -(kv[1][2] or 0))
    return qe, nse[:limit], bse[:limit]
