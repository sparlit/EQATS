# -*- coding: utf-8 -*-
"""FILL-2020 Phase 4: fill consolidated PAT = standalone PAT (SEBI LODR Reg-33 no-sub identity)
for individually-verified (company, quarter) CELLS.

Differs from scripts/apply_nosub_constd{,2}.py, which take a company list x a shared quarter list.
The Phase-4 PAT residue is scattered: each cell is its own company/quarter pair with its own
evidence, so the target here is an explicit cell list.

WHY THESE CELLS (audited 2026-08-06). Each is an INTERIOR hole in a series whose consolidated
column is otherwise the no-sub identity copy of standalone: in every quarter surrounding the gap
con == std to the paisa, and each company only begins to DIVERGE at the quarter it actually
acquires a consolidatable subsidiary. That divergence-onset date, read straight out of our own
sf_fundamentals series, independently corroborates external evidence of when each company's first
subsidiary appeared -- so at the gap quarter there was nothing to consolidate and con == std.

  ICICIGI    Dec-2019  con==std in ALL 26 stored quarters, never diverges (pure identity series).
  SCHAEFFLER Dec-2019  diverges 2023-09; sole subsidiary (KRSV) has audited financials only FY23+.
  TCIEXP     Dec-2019  diverges 2024-06; no subsidiary referenced in the Dec-2019 filing.
  BASF       Mar-2020  diverges 2020-06; first subsidiary acquired 18-Aug-2020, after this quarter.

  KTKBANK    Dec-2019  ADDED 2026-08-06 when the user reversed the non-banks-only rule to "include
  SOUTHBANK  Dec-2019  banks everywhere". These two are no longer resting on our own (possibly
    derived) identity quarters -- the earlier "only 2 identity quarters, too thin" objection was an
    artifact of judging them from stored data alone. The NSE filing index answers it directly
    (§54b E1-E5, all five verified for both): a standalone result IS listed for Dec-2019, NO
    consolidated one is, and the gap precedes the company's FIRST consolidated filing ever --
    KTKBANK 2020-09-30 (95 filings), SOUTHBANK 2021-06-30 (89 filings). Post-Apr-2019 that is the
    exchange's own record that there was nothing to consolidate (§51a). No quarter at or before the
    gap contradicts the identity. Corroboration: KTKBANK's first subsidiary, KBL Services Ltd, was
    incorporated in 2020 -- after this quarter.

DELIBERATELY EXCLUDED (same audit, left null on purpose -- do not "helpfully" add them):
  IOB 2019-2021 (9 cells) -- con is null for every quarter Mar-2018..Dec-2021, but when IOB does
    report consolidated (from Mar-2022) it DIVERGES from standalone (551.78 vs 552.38). It has real
    consolidation differences, so con=std would be fabrication, not an identity.
  HDFC/IDFC/TV18BRDCST/GSPL -- merger casualties; the gap quarter has no std either and the series
    ends there. Nothing to copy from.
  SPICEJET Jun/Sep-2020 -- std gaps; the filing exists but its comparatives do not reconcile with
    our stored values (FY20 restated), so no anchored value can be derived.

Fill-only: never touches a non-null con. Writes docs/sf_fundamentals.json + scripts/fundamentals.json
and journals per-cell provenance to scripts/nosub_pat_fills.json (tracked).

Run:  python -X utf8 scripts/fill2020_tools/apply_nosub_pat_cells.py [--dry]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(ROOT, "scripts", "fundamentals.json")
LEDGER = os.path.join(ROOT, "scripts", "nosub_pat_fills.json")

# (symbol, quarter_end, evidence) -- evidence is journalled per cell
CELLS = [
    ("ICICIGI", 20191231,
     "no-sub-identity; con==std in all 26 stored qtrs, never diverges"),
    ("SCHAEFFLER", 20191231,
     "no-sub-identity; con diverges only from 20230930 (KRSV subsidiary FY23+)"),
    ("TCIEXP", 20191231,
     "no-sub-identity; con diverges only from 20240630; no subsidiary in Dec-2019 filing"),
    ("BASF", 20200331,
     "no-sub-identity; con diverges only from 20200630; first subsidiary acquired 2020-08-18"),
    # banks — added 2026-08-06 on the user's "include banks everywhere" call; §54b E1-E5 verified
    ("KTKBANK", 20191231,
     "no-sub-identity; NSE index 95 filings: standalone listed for 20191231, no consolidated, "
     "first consolidated ever 20200930; no contradiction at/before the gap (E1-E5)"),
    ("SOUTHBANK", 20191231,
     "no-sub-identity; NSE index 89 filings: standalone listed for 20191231, no consolidated, "
     "first consolidated ever 20210630; no contradiction at/before the gap (E1-E5)"),
]


def apply(path, dry):
    """Fill-only con=std for the target cells. Returns (filled, journal, skipped)."""
    d = json.load(open(path))
    filled, journal, skipped = 0, {}, []
    for sym, qe, why in CELLS:
        rows = d.get(sym)
        if not rows:
            skipped.append((sym, qe, "nosym"))
            continue
        r = {row[0]: row for row in rows}.get(qe)
        if not r:
            skipped.append((sym, qe, "norow"))
            continue
        while len(r) < 5:
            r.append(None)
        if r[1] is None:                       # nothing to copy FROM
            skipped.append((sym, qe, "nostd"))
            continue
        if r[3] is not None:                   # fill-only: never overwrite
            skipped.append((sym, qe, "hascon"))
            continue
        r[3] = r[1]
        if r[4] is None:
            r[4] = r[2]                        # same filing -> same announce date
        filled += 1
        journal["%s|%d" % (sym, qe)] = {"con": r[3], "ann": r[4], "src": "no-sub-identity",
                                        "basis": "con=std", "evidence": why,
                                        "applied": "2026-08-06 FILL-2020 Phase 4"}
    if not dry:
        json.dump(d, open(path, "w"), separators=(",", ":"))
    return filled, journal, skipped


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    f1, j1, s1 = apply(DOCS, dry)
    f2, j2, s2 = apply(MIRROR, dry)
    print("docs filled %d | mirror filled %d%s" % (f1, f2, "  (DRY RUN)" if dry else ""))
    for s in (s1, s2):
        if s:
            print("  skipped:", s)
    if not dry and j1:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(j1)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d cells -> %s" % (len(j1), os.path.basename(LEDGER)))
