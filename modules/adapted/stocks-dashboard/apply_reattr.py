# -*- coding: utf-8 -*-
"""Apply the attributable-to-owners switch to docs/sf_fundamentals.json using the owners' figures
computed from the local XBRL cache (_reattr_owners.json: "SYMBOL|qe" -> owners cr). Sets npCon
(consolidated profit) to the parent owners' share wherever it differs from the stored total PAT;
leaves everything else (standalone, no-minority, backfilled quarters) untouched. Atomic write.

Run: python -X utf8 apply_reattr.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")

def main():
    live = json.load(open(F))
    owners = json.load(open(os.path.join(HERE, "_reattr_owners.json")))
    changed = 0; stocks = set()
    for sym, arr in live.items():
        for row in arr:                                   # [qe, npStd, annStd, npCon, annCon]
            a = owners.get("%s|%d" % (sym, row[0]))
            if a is not None and row[3] is not None and abs(a - row[3]) > 0.5:
                row[3] = a; changed += 1; stocks.add(sym)
    tmp = F + ".tmp"; json.dump(live, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, F)
    print("Applied attributable-to-owners to %d consolidated quarters across %d stocks." % (changed, len(stocks)))

if __name__ == "__main__":
    main()
