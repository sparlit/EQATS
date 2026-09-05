# -*- coding: utf-8 -*-
"""FILL-2020: ADVANTA standalone PAT, Mar-2015 + Sep-2015 -- GATE X (two-source cross-check).

These two cells failed both detres gates and the failure was MISDIAGNOSED as "genuinely
inconsistent year" (runbook §52c, corrected same day). The real story, from the NSE archive
detail pages: **ADVANTA is a CALENDAR-YEAR filer** -- the pages declare "First/Third Quarter,
Financial Year 01-Jan-2015 To 31-Dec-2015" -- so the Apr-Mar FY-sum identity was summing across
two of its fiscal years and could never reconcile. The EPS recon failure (9%) is the quarters'
extraordinary items (each prints two divergent EPS figures).

GATE X instead (PRE2015_CAMPAIGN standard: detres PAT and NSE-page PAT agree within
max(0.05cr, 0.5%)): the same as-filed result served by two independent exchange archives.

  20150331  std 10.59 cr   detres NP 105.9 mn == NSE 1,058.96 lakh ("Profit/(Loss) from
            ordinary activities after tax", Non-Consolidated, Non-Cumulative, Q1 CY2015).
            Share capital cross-match: NSE 1,846.30 lakh == detres Equity Capital 184.63 mn.
  20150930  std 15.17 cr   detres NP 151.74 mn == NSE 1,517.38 lakh (Q3 CY2015, exact).
            Share capital: NSE 2,010.91 lakh == detres 201.09 mn.

NSE sources (delisted symbols are served -- SATYAMCOMP precedent):
  financial_res_ADVANTA_127466.html (Mar-15), financial_res_ADVANTA_1002369.html (Sep-15)
  via corporates-financial-results?index=equities&symbol=ADVANTA&period=Quarterly.

Fill-only; journals to scripts/std_pat_detres_fills.json.
Run:  python -X utf8 scripts/fill2020_tools/apply_advanta_std.py [--apply]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(ROOT, "scripts", "fundamentals.json")
LEDGER = os.path.join(ROOT, "scripts", "std_pat_detres_fills.json")

CELLS = {
    20150331: (10.59, "GATE-X: detres 105.9mn == NSE financial_res_ADVANTA_127466.html "
                      "1058.96 lakh (Q1 CY2015, Non-Consolidated); share-capital cross-match"),
    20150930: (15.17, "GATE-X: detres 151.74mn == NSE financial_res_ADVANTA_1002369.html "
                      "1517.38 lakh (Q3 CY2015, Non-Consolidated, exact); share-capital cross-match"),
}


def apply(path, dry):
    d = json.load(open(path))
    byqe = {r[0]: r for r in d.get("ADVANTA", [])}
    filled, skipped, journal = 0, [], {}
    for qe, (val, why) in sorted(CELLS.items()):
        r = byqe.get(qe)
        if not r:
            skipped.append((qe, "norow"))
            continue
        while len(r) < 5:
            r.append(None)
        if r[1] is not None:
            skipped.append((qe, "has-std=%s" % r[1]))
            continue
        r[1] = val
        filled += 1
        journal["ADVANTA|%d" % qe] = {"std": val, "src": "gate-x-detres+nse-archive",
                                      "basis": "standalone (calendar-year filer)",
                                      "evidence": why,
                                      "applied": "2026-08-06 FILL-2020 std-2015-2020"}
    if not dry:
        json.dump(d, open(path, "w"), separators=(",", ":"))
    return filled, skipped, journal


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    f1, s1, j = apply(DOCS, dry)
    f2, s2, _ = apply(MIRROR, dry)
    print("docs %d | mirror %d%s" % (f1, f2, "  (DRY RUN)" if dry else ""))
    for s in (s1, s2):
        if s:
            print("   skipped:", s)
    if not dry and j:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(j)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d" % len(j))
