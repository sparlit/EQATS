# -*- coding: utf-8 -*-
"""Replace crore-rounded cells with the EXACT filing figure once the reader can reach them.

User, 2026-08-06: *"i am not saying u to fill empties from screener.in but fill it on ur own"*.
These three were written crore-rounded from screener because my reader could not get into the
filing. It can now (§61a modes 2/3/4 + §62 geometric columns), so the placeholders are replaced by
what the company actually printed. Every exact value confirms the rounded one it replaces, which is
also the cross-check that the new reader is right:

    AIIL        1452 -> 1451.81   own-season p14, "Revenue from operations"
    CYIENT      1909 -> 1909.20   own-season p2,  "(a) Revenue from contracts with customers",
                                  Rs MILLION (19,092), column x=420.6 anchored on the owners row
                                  "Shareholders of the Company" 1704 = our stored con PAT 170.4,
                                  and the neighbouring column 1223 = our stored Dec-2024 122.3
    WAAREEENER  4004 -> 4003.93   own-season p6,  "(a) Revenue from operations"

This is the ONLY sanctioned overwrite in the campaign: same cell, same basis, strictly better
provenance, and the new value must round to the old one or the upgrade is refused.

Run: python -X utf8 scripts/fill2020_tools/upgrade_rounded_cells.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")
QE = "20250331"

UP = {
    "AIIL":       (1452.0, 1451.81, "own-season p14 'Revenue from operations'"),
    "CYIENT":     (1909.0, 1909.20, "own-season p2 '(a) Revenue from contracts with customers', "
                                    "Rs million 19092, col x=420.6 anchored on 'Shareholders of the "
                                    "Company' 1704 == stored con PAT 170.4; adjacent col 1223 == "
                                    "stored Dec-2024 con PAT 122.3"),
    "WAAREEENER": (4004.0, 4003.93, "own-season p6 '(a) Revenue from operations'"),
}


def main():
    dry = "--apply" not in sys.argv
    journal = {}
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"),
                 os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        n = 0
        for sym, (old, new, ev) in sorted(UP.items()):
            row = (d.get(sym) or {}).get(QE)
            if not row or len(row) < 2:
                print("  %s: no row" % sym)
                continue
            cur = row[1]
            if cur is None:
                print("  %s: empty, not an upgrade -- skipped" % sym)
                continue
            if abs(cur - old) > 0.011:
                print("  %s: holds %s, expected the rounded %s -- REFUSED" % (sym, cur, old))
                continue
            if round(new) != round(old):
                print("  %s: exact %s does not round to %s -- REFUSED" % (sym, new, old))
                continue
            row[1] = new
            d[sym][QE] = row
            n += 1
            journal["%s|%s" % (sym, QE)] = {
                "revC": new, "precision": "filing-exact", "supersedes": old,
                "src": "bse-filing-pdf, geometric column read (§62)",
                "evidence": ev, "applied": "2026-08-06 rounded->exact upgrade"}
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d cells" % (os.path.basename(path),
                                     "would upgrade" if dry else "upgraded", n))
    if not dry and journal:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))
    if dry:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
