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
"""Moneycontrol ANNUAL series + the FY-identity gate for companies our anchors cannot reach.

WHY THIS EXISTS. The anchor gate proves a Moneycontrol series is OUR company's series by making it
reproduce >=3 of our own stored quarters near the target. That is the right test — and it is useless
for exactly the companies with the widest gaps, because it needs six stored quarters on that basis
to mean anything. Measured 2026-08-11: 1,441 (symbol, basis) pairs and 34,993 open cells sit below
that floor, 2,164 of them member-scoped real gaps. They were never ATTEMPTED — not refused, not
absent, simply skipped before a request went out. That is the largest untried block left.

THE SUBSTITUTE TEST, and it needs nothing from our store: make the SOURCE prove itself internally.

    sum(the four quarters of a financial year)  ==  that financial year's annual, same label
      -- both from Moneycontrol, quarterly_results_responsive vs yearly_results_responsive.

A series that reconciles against its own annual is internally consistent: the quarters are the same
company, the same basis and the same definition as the annual, none is a duplicate or a stray, and
none carries a scale error (a lakh-vs-crore quarter blows the sum apart). It does NOT prove the
series is our company — symbol resolution does that (§49, verified NSE symbol + sc_id field).

★ THE FY IS READ FROM THE ANNUAL'S OWN LABEL, NEVER ASSUMED TO BE APR-MAR. `yrc0` is "Mar '26" or
"Dec '25"; the four quarters summed are the four ending AT that month. Assuming Apr-Mar silently
mis-sums every December-year-end company (memory: feedback-site-fy-identity-catches-restatements).

★★ WHAT THIS GATE CANNOT DO, stated plainly: it cannot choose the revenue ROW. Net Sales and Total
Income each reconcile against their own annual, so the identity holds for BOTH definitions and
distinguishes neither. Picking the row still needs our stored quarters — which is why the caller
scores labels across BOTH bases of the company (our storage convention is a property of the company,
not of the basis) and refuses the cell outright when the company has no stored quarter anywhere.
Guessing a row here would reproduce the SIEMENS defect at scale (§85: Net Sales 2753.3 vs Total
Income 2825.9, both real rows, both plausible, one wrong).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mc_quarterly_fetch as MC  # noqa: E402

ANNUAL_URL = (
    "https://appfeeds.moneycontrol.com/jsonapi/stocks/yearly_results_responsive"
    "?sc_id=%s&type_format=%s&start=0&limit=%d"
)
AFMT = {"std": "yearly", "con": "cons_yearly"}
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def annual_raw(code, basis, limit=30):
    """Rows of the annual table, disk-cached. Cache key includes the limit (§ silent caps)."""
    cache = os.path.join(MC.CACHE, "%s_%sY_%d.json" % (code, basis, limit))
    if os.path.exists(cache):
        try:
            return json.load(open(cache))
        except Exception:
            pass
    body = MC.get(ANNUAL_URL % (code, AFMT[basis], limit))
    if not body:
        return []
    try:
        rows = json.loads(body).get("data") or []
    except Exception:
        return []
    if rows:
        json.dump(rows, open(cache, "w"))
    return rows


def fy_end_of(label):
    """'Mar \\'26' -> (2026, 3). The year-END month comes from the label, never assumed."""
    if not label or "'" not in label:
        return None
    mon = label.strip()[:3]
    if mon not in MONTHS:
        return None
    try:
        yy = int(label.strip().split("'")[-1])
    except ValueError:
        return None
    return (2000 + yy if yy < 80 else 1900 + yy), MONTHS[mon]


def quarters_of_fy(end_year, end_month):
    """The four quarter-ends of the FY ending at (end_year, end_month), newest last."""
    out = []
    y, m = end_year, end_month
    for _ in range(4):
        out.append(y * 10000 + m * 100 + (31 if m in (1, 3, 5, 7, 8, 10, 12) else 30))
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return sorted(out)


def fy_identity(code, basis, label, limit=400, tol_rel=0.005, tol_abs=3.0):
    """{fy_end_year: (ok, annual, qsum, quarters)} for every FY the annual table covers and the
    quarterly table fully spans. tol defaults are calibrated in calibrate_fy_identity.py."""
    q = {}
    for row in MC.series_raw(code, basis, limit):
        qe = MC.qe_of(row.get("yrc0"))
        v = MC.row_value(row, label)
        if qe and v is not None:
            q[qe] = v
    out = {}
    for row in annual_raw(code, basis):
        fe = fy_end_of(row.get("yrc0"))
        av = MC.row_value(row, label)
        if not fe or av is None:
            continue
        qs = quarters_of_fy(*fe)
        if not all(x in q for x in qs):
            continue
        s = sum(q[x] for x in qs)
        ok = abs(s - av) <= max(tol_abs, tol_rel * max(abs(av), abs(s)))
        out[fe[0]] = (ok, av, round(s, 2), qs)
    return out
