# -*- coding: utf-8 -*-
"""TTKPRESTIG: the Jun-2019 consolidated row is the Jun-2018 COLUMN — fix the row, then fill the hole.

FOUND while filling TTKPRESTIG 20180630 for the con-params L4 campaign, and it is the reason that
fill could not ship alone: writing the Jun-2018 value while the Jun-2019 row still holds the same
number would have left two identical adjacent quarters, which is the adjacent-quarter duplicate
class this project has healed before (runbook 74/79). One document settles both.

THE DOCUMENT. TTK Prestige Ltd, "Statement of UnAudited Financial Results for the Quarter ended
30th June 2019" (BSE announcement 13-Aug-2019, attachment saved as TTKPRESTIG_q1fy20.pdf), page 2,
declared "Rs.in Crores". Read by rendering the page at 2.4x and looking at it -- the text layer of
this scan is mangled ("TIK PRESTIGE LIMITED", "Corporate Qff,ce").

Its CONSOLIDATED block carries three quarter columns, in this order:

    CONSOLIDATED            30.6.2019    31.3.2019    30.6.2018      Year ended 31.03.2019
    I   Revenue from ops       461.20       482.17       448.58              2106.91
    IX  Profit for the period    35.81        44.77        35.49              192.35
    XVI Profit attributable to
        - Owners                35.81        44.77        35.49              192.35
        - Non controlling int.       -            -            -                   -

and our store holds, at **20190630**: conPAT 35.49, revC 448.58, opC 55.72 -- the 30.6.**2018**
column on all three quantities at once. Three independent figures agreeing rules out coincidence.
The operating-profit figure confirms it arithmetically: this statement's own line items give
448.58 - (400.13 - 0.93 - 6.34) = 55.72 for the Jun-2018 column and
461.20 - (413.21 - 0.80 - 7.36) = 56.15 for the Jun-2019 one.

ANCHORS proving the document and the column geometry, from the STANDALONE block of the same page:
30.6.2018 revenue 418.87 == stored rev_std EXACT and profit 35.90 == stored stdPAT EXACT;
30.6.2019 revenue 433.60 == stored rev_std EXACT and profit 36.47 == stored stdPAT EXACT.
The consolidated 31.3.2019 column prints 44.77 against our stored conPAT 44.76 (1 paisa).

WHAT THIS DOES
  20190630  CORRECTION  conPAT 35.49 -> 35.81   revC 448.58 -> 461.20   opC 55.72 -> 56.15
  20180630  FILL        conPAT None  -> 35.49   revC None   -> 448.58   opC None -> 55.72
Both quarters take annCon 20190813 -- this one filing is where both numbers were published.
The correction is journalled in pat_defects.json / rev_defects.json (both registered in
verify_fills_live.py, so a rebuild that re-lands the shifted column trips the detector) and the
fill's provenance goes in conpat_filing_fills.json alongside the rest of the L4 wave.

Run: python3 -X utf8 scripts/fill2020_tools/fix_ttkprestige_jun_column_shift.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
SYM = "TTKPRESTIG"
ANN = 20190813
TOL = 0.011

SRC = ("TTK Prestige Ltd 'Statement of UnAudited Financial Results for the Quarter ended 30th June "
       "2019' (BSE announcement 13-Aug-2019, attachment TTKPRESTIG_q1fy20.pdf) p2, CONSOLIDATED "
       "block, columns 'Quarter Ended 30.6.2019 / 31.3.2019 / 30.6.2018' — statement declares "
       "'Rs.in Crores'. Scanned page with a mangled text layer; read by rendering at 2.4x.")
ANCHOR = ("SAME PAGE, STANDALONE block, four exact reproductions of stored cells: 30.6.2018 revenue "
          "418.87 == stored rev_std and profit 35.90 == stored stdPAT; 30.6.2019 revenue 433.60 == "
          "stored rev_std and profit 36.47 == stored stdPAT. Consolidated 31.3.2019 prints 44.77 "
          "against stored conPAT 44.76 (1 paisa).")
DEFECT = ("column shift: the stored 20190630 consolidated row held the printed 30.6.2018 column on "
          "all three quantities at once (PAT 35.49, revenue 448.58, operating profit 55.72), while "
          "the printed 30.6.2019 column is 35.81 / 461.20 / 56.15. Three figures agreeing rules out "
          "coincidence; opC reproduces from the statement's own line items on both columns.")

# qe -> (conPAT, revC, opC)
CORRECT = {20190630: (35.81, 461.20, 56.15)}
FILL = {20180630: (35.49, 448.58, 55.72)}
WAS = {20190630: (35.49, 448.58, 55.72)}


def load(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    apply = "--apply" in sys.argv
    paths = {
        "fund_d": os.path.join(ROOT, "docs", "sf_fundamentals.json"),
        "fund_s": os.path.join(SCRIPTS, "fundamentals.json"),
        "rev_d": os.path.join(ROOT, "docs", "sf_revop.json"),
        "rev_s": os.path.join(SCRIPTS, "revop_fundamentals.json"),
        "patdef": os.path.join(SCRIPTS, "pat_defects.json"),
        "revdef": os.path.join(SCRIPTS, "rev_defects.json"),
        "prov": os.path.join(SCRIPTS, "conpat_filing_fills.json"),
    }
    st = {k: load(v) for k, v in paths.items()}
    rc = 0

    def fund_rows(qe):
        out = []
        for k in ("fund_d", "fund_s"):
            row = next((r for r in (st[k].get(SYM) or []) if r and r[0] == qe), None)
            if row is not None:
                out.append((k, row))
        return out

    def rev_rows(qe):
        return [(k, (st[k].get(SYM) or {}).get(str(qe)))
                for k in ("rev_d", "rev_s") if (st[k].get(SYM) or {}).get(str(qe))]

    # ---- 1. the correction. Guard on the value we measured as wrong: if the store no longer holds
    #         it, someone else has been here and this script must not guess what they meant.
    for qe, (con, rev, op) in CORRECT.items():
        wcon, wrev, wop = WAS[qe]
        for label, row in fund_rows(qe):
            if row[3] is None or abs(row[3] - wcon) > TOL:
                print("  !! %s %s conPAT is %s, expected the defective %s — stopping"
                      % (label, qe, row[3], wcon))
                return 1
            print("  %-8s %s conPAT %s -> %s" % (label, qe, row[3], con))
            if apply:
                row[3], row[4] = con, ANN
        for label, row in rev_rows(qe):
            for slot, was, now, name in ((1, wrev, rev, "revC"), (3, wop, op, "opC"), (5, wcon, con, "patC")):
                cur = row[slot] if len(row) > slot else None
                if cur is None or abs(cur - was) > TOL:
                    print("  !! %s %s %s is %s, expected %s — stopping" % (label, qe, name, cur, was))
                    return 1
                print("  %-8s %s %-4s %s -> %s" % (label, qe, name, cur, now))
                if apply:
                    row[slot] = now

    # ---- 2. the fill (fill-only: never overwrite a non-null slot)
    for qe, (con, rev, op) in FILL.items():
        for label, row in fund_rows(qe):
            if row[3] is not None and abs(row[3] - con) > TOL:
                print("  !! %s %s conPAT already holds %s — stopping" % (label, qe, row[3]))
                return 1
            print("  %-8s %s conPAT %s -> %s (fill)" % (label, qe, row[3], con))
            if apply:
                row[3], row[4] = con, ANN
        for label, row in rev_rows(qe):
            for slot, now, name in ((1, rev, "revC"), (3, op, "opC"), (5, con, "patC")):
                cur = row[slot] if len(row) > slot else None
                if cur is not None and abs(cur - now) > TOL:
                    print("  !! %s %s %s already holds %s — stopping" % (label, qe, name, cur))
                    return 1
                print("  %-8s %s %-4s %s -> %s (fill)" % (label, qe, name, cur, now))
                if apply:
                    row[slot] = now

    # ---- 3. journal both sides
    st["patdef"].setdefault(SYM, {})["20190630"] = {
        "correct_pat_con": CORRECT[20190630][0], "stored_pat_con": WAS[20190630][0],
        "defect": DEFECT, "source": SRC, "anchor": ANCHOR,
        "campaign": "con-params-L4", "when": "2026-08-18",
    }
    st["revdef"].setdefault(SYM, {})["20190630"] = {
        "correct_rev": CORRECT[20190630][1], "bad_rev": WAS[20190630][1], "basis": "con",
        "defect": DEFECT, "source": SRC, "anchor": ANCHOR,
    }
    st["prov"]["%s|20180630|con" % SYM] = {
        "con": FILL[20180630][0], "annCon": ANN, "basis": "con",
        "src": SRC, "anchor": ANCHOR,
        "row": "IX 'Profit/(Loss) for the period from Continuing operations' = XVI 'Profit "
               "attributable to - Owners' (NCI prints '-'), consolidated column 30.6.2018",
        "printed": "35.49", "unit": "Rs.in Crores", "read_by": "vision (rendered 2.4x, p2)",
        "carrying_filing": True, "con_total": FILL[20180630][0], "con_nci": 0.0,
        "paired_correction": "%s|20190630 — the same column was sitting in the Jun-2019 row; "
                             "filling this cell without that fix would have left two identical "
                             "adjacent quarters" % SYM,
        "campaign": "con-params-L4", "when": "2026-08-18",
    }
    st["prov"]["%s|20180630|con_rev" % SYM] = {
        "rev_con": FILL[20180630][1], "basis": "con", "src": SRC, "anchor": ANCHOR,
        "row": "I 'Revenue from operations(Net of Discounts)', consolidated column 30.6.2018",
        "unit": "Rs.in Crores", "read_by": "vision (rendered 2.4x, p2)",
        "campaign": "con-params-L4", "when": "2026-08-18",
    }

    if not apply:
        print("\nDRY RUN — re-run with --apply to write")
        return rc
    for k in ("fund_d", "fund_s", "rev_d", "rev_s"):
        json.dump(st[k], open(paths[k], "w"), separators=(",", ":"))
    for k in ("patdef", "revdef", "prov"):
        json.dump(st[k], open(paths[k], "w"), indent=1, sort_keys=True)
    print("\nWROTE 7 files.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
