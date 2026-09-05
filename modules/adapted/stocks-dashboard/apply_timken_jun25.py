# -*- coding: utf-8 -*-
"""REV-CON close-out: TIMKEN 2025-06 consolidated revenue = 822.18, from the Jun-2026 filing's
year-ago column (NSE announcement PDF, digital text layer).

Why every automated route missed it:
  * Timken began consolidating in FY2025 but filed STANDALONE-ONLY quarterly XBRLs for Jun-2025
    and Sep-2025 (the integrated-filing index lists no consolidated row for either; its first
    consolidated XBRL is Dec-2025, filed 04-Feb-2026). So there is no XBRL to fetch (§54a blind),
    and the identity route correctly refuses on E4/E5 (con PAT 108.43 != std 104.22 — Timken
    really consolidates; copying std would fabricate).
  * The Jun-2025 filing's own PDF (TIMKEN_01082025105447_Letter.pdf) is a scan with no text layer.
  * Integrated XBRLs carry ONLY the current quarter (verified: the Jun-2026 con instance has just
    2026-04-01..2026-06-30 contexts), so no comparative context exists to mine.

THE READ (04-Aug-2026 "Outcome of Board Meeting" PDF, TIMKEN_04082026200709_SEIntimation0408
Outcome.pdf, page 5 = "STATEMENT OF UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER
ENDED JUNE 30, 2026", Rs in Million -> /10):
    columns:                  Q 30-06-2026 | Q 31-03-2026 | Q 30-06-2025 | FY 31-03-2026
    Revenue from operations       9,433.20 |    10,898.26 |     8,221.79 |     34,780.29
    Net Profit after tax          1,196.59 |     1,583.05 |     1,084.25 |      4,148.85

COLUMN ANCHORS (§58) — every printed column reproduces a stored value exactly:
    rev  943.32 == stored 20260630 revC | rev 1,089.83 == stored 20260331 revC
    PAT  119.66 == stored 20260630 patC | PAT   158.31 == stored 20260331 patC
    TARGET column PAT 108.43 (1,084.25/10) == stored 20250630 patC  (exact)
FY-IDENTITY (§45), an independent route inside the same document:
    FY26 con 3,478.03 − (Sep 786.35 + Dec 779.67 + Mar 1,089.83 stored) = 822.18  == the read
CROSS-BASIS CONTROL (P4): the standalone page's Jun-2025 column shows rev 8,088.17 -> 808.82
    == stored 20250630 revS and PAT 1,042.24 -> 104.22 == stored 20250630 patS (both exact).
Note: the filing marks the Jun-2025 consolidated comparatives as management-compiled, not
auditor-reviewed (first year of consolidation) — it is still the company's own filed figure.

Fill-only, revenue slot (1) only.
Run: python -X utf8 scripts/fill2020_tools/apply_timken_jun25.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")

SYM, QE, VAL = "TIMKEN", "20250630", 822.18
EV = ("year-ago column of the 04-Aug-2026 NSE outcome PDF (digital text, Rs Mn/10); anchors: "
      "Jun-26 col rev 943.32+PAT 119.66, Mar-26 col rev 1089.83+PAT 158.31, target col PAT "
      "108.43 — all == stored exactly; FY-identity 3478.03-786.35-779.67-1089.83=822.18 agrees; "
      "std-page control 808.82/104.22 == stored")


def main():
    dry = "--apply" not in sys.argv
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"),
                 os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        row = d.get(SYM, {}).get(QE)
        if not row:
            print("%-30s no row" % os.path.basename(path))
            continue
        while len(row) < 9:
            row.append(None)
        if row[1] is not None:
            print("%-30s already filled: %s" % (os.path.basename(path), row[1]))
            continue
        row[1] = VAL
        d[SYM][QE] = row
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s revC=%s" % (os.path.basename(path),
                                    "would fill" if dry else "filled", VAL))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led["%s|%s" % (SYM, QE)] = {"revC": VAL, "src": "nse-outcome-pdf-yearago-column",
                                    "evidence": EV, "applied": "2026-08-10 rev-con close-out"}
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled -> %s" % os.path.basename(LEDGER))
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
