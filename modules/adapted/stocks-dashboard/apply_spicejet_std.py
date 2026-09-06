# -*- coding: utf-8 -*-
"""FILL-2020 Phase 4: SPICEJET standalone PAT, the 3 cells the automated route could not reach.

These sat in the campaign's "std gap" residue because SpiceJet filed chronically late (COVID
relaxations pushed Q1 FY21 to a 15-Sep-2020 board meeting) so the +/-6-day window around the stored
announce date found no filing at all, and because the PDFs are OCR-mangled ("Nel Profiil",
"(l.onJliirofil for Utt quuter/yur"), which defeats row-keyword matching.

EVERY VALUE IS DOUBLE-ANCHORED. Scale is "Rupees in millions" throughout -> /10 = crore.

  20200630  std -593.41   (-5,934.09 mn)
     anchor A: SpiceJet's OWN Q1 filing (board meeting 15-Sep-2020) prints it, and that filing's
               comparative columns match our stored series EXACTLY -- Mar-2020 std -807.08 and
               Jun-2019 std +261.67. Two stored comparatives locking = the strongest form of §6 anchor.
     anchor B: the Q2 filing (11-Nov-2020) independently prints the same -5,934.09 as its
               prior-quarter column, and its six-month total reconciles exactly:
               -593.409 + -112.594 = -706.003 == the printed 6M -7,060.03 mn.

  20200930  std -112.59   (-1,125.94 mn)
     anchor A: the 6M = SUM(Q) identity above (exact to the paisa).
     anchor B: the SAME PDF's consolidated owners row reproduces our stored con for all three
               printed quarters -- Sep-20 -105.61, Jun-20 -600.52, Sep-19 -461.22 -- which proves the
               document, the /10 scale and the column order before the standalone column is read.

  20230930  std -431.54   (-4,315.41 mn)
     anchor A: PBT - tax = PAT in-column identity (-4,315.41 - nil).
     anchor B: the same filing's consolidated total PAT -4,494.30 mn = -449.43 == our stored con for
               that quarter exactly, and its 6M column reconciles (-4,494.30 + 1,976.15 = -2,518.15
               vs printed -2,518.05, rounding). Document/scale/column validated before reading std.

ANNOUNCE DATES use the VERIFIED filing date, which is later than the stored con announce date on
each row (20200915 vs 20200810; 20201111 vs 20201105; 20231212 vs 20231105). Later is the safe
direction for the §12 point-in-time gate -- it never claims a number was public earlier than proven.

NOTED, NOT CHANGED (pre-existing, out of scope for a fill -- correcting is the §2b procedure):
  - SPICEJET 20190930 std is stored -461.22, which equals the CONSOLIDATED figure; the standalone
    statement prints -462.58. Looks like the std cell was populated from the con column.
  - SPICEJET 20230930 con is stored -449.43 = TOTAL consolidated PAT, but the project basis is
    owners-attributable, which that filing prints as -448.99.

Fill-only. Writes docs/sf_fundamentals.json + scripts/fundamentals.json, journals to
scripts/nosub_pat_fills.json (tracked).

Run:  python -X utf8 scripts/fill2020_tools/apply_spicejet_std.py [--apply]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(ROOT, "scripts", "fundamentals.json")
LEDGER = os.path.join(ROOT, "scripts", "nosub_pat_fills.json")

SYM = "SPICEJET"
# qe -> (std_pat_crore, announce_yyyymmdd, anchor note)
CELLS = {
    20200630: (-593.41, 20200915,
               "own Q1 filing 15-Sep-2020; its comparatives match stored Mar-20 -807.08 and "
               "Jun-19 +261.67 exactly; Q2 filing repeats it and 6M=sumQ reconciles"),
    20200930: (-112.59, 20201111,
               "6M=sumQ exact (-593.409 + -112.594 = -706.003); same PDF's con owners row "
               "reproduces stored con -105.61/-600.52/-461.22"),
    20230930: (-431.54, 20231212,
               "PBT-tax=PAT in-column (-4,315.41, nil tax); same filing's con total -449.43 "
               "matches stored con exactly, 6M column reconciles"),
}


def apply(path, dry):
    d = json.load(open(path))
    rows = d.get(SYM)
    if not rows:
        return 0, [(SYM, "nosym")], {}
    byqe = {r[0]: r for r in rows}
    filled, skipped, journal = 0, [], {}
    for qe, (val, ann, why) in sorted(CELLS.items()):
        r = byqe.get(qe)
        if not r:
            skipped.append((qe, "norow"))
            continue
        while len(r) < 5:
            r.append(None)
        if r[1] is not None:                       # fill-only: never overwrite
            skipped.append((qe, "has-std=%s" % r[1]))
            continue
        r[1] = val
        if r[2] is None:
            r[2] = ann
        filled += 1
        journal["%s|%d" % (SYM, qe)] = {"std": val, "ann": ann, "src": "bse-filing-read",
                                        "basis": "standalone PAT", "evidence": why,
                                        "applied": "2026-08-06 FILL-2020 Phase 4"}
    if not dry:
        json.dump(d, open(path, "w"), separators=(",", ":"))
    return filled, skipped, journal


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    f1, s1, j = apply(DOCS, dry)
    f2, s2, _ = apply(MIRROR, dry)
    print("docs filled %d | mirror filled %d%s" % (f1, f2, "   (DRY RUN)" if dry else ""))
    for s in (s1, s2):
        if s:
            print("   skipped:", s)
    if not dry and j:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(j)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d cells -> %s" % (len(j), os.path.basename(LEDGER)))
