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
"""Regenerate _wf_gaps.json (current gaps across the 2024 union, 2020Q4..Mar26) and _wf_bins.json
(balanced agent partition: big insurers isolated, then non-insurers packed by std-weight).
Run between chunks so already-filled cells drop out. Usage: python -X utf8 _wf_regap.py
"""
import functools
import json
import operator

data = json.load(open("../docs/sf_fundamentals.json"))
union = set(json.load(open("_full_union_2024.json")))
INSURERS = {
    "LICI",
    "SBILIFE",
    "HDFCLIFE",
    "ICICIPRULI",
    "ICICIGI",
    "GICRE",
    "NIACL",
    "STARHEALTH",
    "GODIGIT",
    "NIVABUPA",
    "MFSL",
}
# Structurally unrecoverable -> exclude from agent partition (documented, don't waste agents):
#  HEXT: delisted Nov-2020 (Baring PE), re-IPO Feb-2025 -> NO exchange filings 2020Q4..2024.
#  PIRAMALFIN: stored series tracks the NBFC (Piramal Finance/PCHFL); pre-2022 NSE filings are PEL
#    (Piramal Enterprises, pre-demerger) and don't reconcile with the series -> ambiguous, manual only.
#  HDFCLIFE: 2 cells left (Q1FY23 std/con) — agents return the RESTATEMENT; need original-PIT read
#    from the local _vpdf/HDFCLIFE_20220630_nse.pdf (deferred to a manual cleanup pass).
#  IOB: 8 con cells 2020Q1-2021 — bank consolidates associate(Odisha Gramya)+JV, so con!=std (no-sub
#    identity invalid), and IOB filed NO consolidated results before FY22. Structurally unrecoverable.
#  SAGILITY: NSE-listed Nov-2024; pre-listing quarters only in IPO prospectus (restated, unanchorable).
EXCLUDE = {"HEXT", "PIRAMALFIN", "IOB", "SAGILITY"}  # HDFCLIFE done 2026-06-21 (original-PIT 365.29/328.79)
QES = [
    y * 10000 + md for y in range(2020, 2027) for md in (331, 630, 930, 1231) if 20200331 <= y * 10000 + md <= 20260331
]


def rowof(rec, q):
    return next((x for x in rec if x[0] == q), None)


gaps = {}
for sym in union:
    if sym in EXCLUDE:
        continue
    rec = data.get(sym)
    if not rec:
        continue
    qmin = min(x[0] for x in rec)
    qmax = max(x[0] for x in rec)
    # span = the company's ACTUAL reporting life [qmin, qmax]. Do NOT force-extend to 20260331:
    # delisted/merged companies (IDFC->IDFCFIRSTB, TV18BRDCST->NETWORK18) end mid-stream and would
    # otherwise get phantom post-death "gaps" that no filing can fill (wastes agents). Latest-quarter
    # gaps for ACTIVE names are the daily cron's job, not this historical backfill.
    span = [q for q in QES if qmin <= q <= qmax]
    g = []
    series = {str(x[0]): [x[1], x[3] if len(x) > 3 else None] for x in rec if 20180101 <= x[0] <= 20260331}
    for q in span:
        r = rowof(rec, q)
        miss = []
        if r is None:
            miss = ["std", "con"]
        else:
            if r[1] is None:
                miss.append("std")
            if (r[3] if len(r) > 3 else None) is None:
                miss.append("con")
        if miss:
            g.append({"qe": q, "miss": miss})
    if g:
        gaps[sym] = {"gaps": g, "series": series}
json.dump(gaps, open("_wf_gaps.json", "w"))
cells = sum(len(gg["miss"]) for v in gaps.values() for gg in v["gaps"])
con = sum(gg["miss"].count("con") for v in gaps.values() for gg in v["gaps"])
std = cells - con
print("gaps: %d companies, %d cells (con %d std %d)" % (len(gaps), cells, con, std))


# partition
def cs(sym):
    c = s = 0
    for gg in gaps[sym]["gaps"]:
        for b in gg["miss"]:
            if b == "con":
                c += 1
            else:
                s += 1
    return c, s


def work(sym):
    c, s = cs(sym)
    return s * 1.0 + c * 0.3


bins = []
for s in ["HDFCLIFE", "ICICIPRULI", "GICRE", "NIACL"]:
    if s in gaps:
        bins.append([s])
tiny = [s for s in ("LICI", "MFSL", "SBILIFE", "ICICIGI", "STARHEALTH", "GODIGIT", "NIVABUPA") if s in gaps]
if tiny:
    bins.append(tiny)
done = set(functools.reduce(operator.iadd, bins, []))
rest = sorted([s for s in gaps if s not in done], key=lambda s: -work(s))
TARGET = 8.0
cur = []
curw = 0
for s in rest:
    w = work(s)
    if cur and (curw + w > TARGET or len(cur) >= 4):
        bins.append(cur)
        cur = []
        curw = 0
    cur.append(s)
    curw += w
if cur:
    bins.append(cur)
json.dump(bins, open("_wf_bins.json", "w"))
print("bins(agents):", len(bins), "| insurer bins:", [i for i, b in enumerate(bins) if any(x in INSURERS for x in b)])
for i, b in enumerate(bins):
    print("  bin%2d (%.1f): %s" % (i, sum(work(x) for x in b), b))
