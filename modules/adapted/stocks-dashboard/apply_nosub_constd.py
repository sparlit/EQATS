# -*- coding: utf-8 -*-
"""Fill consolidated = standalone (accounting identity) for the 19 N500 companies that filed
standalone-only all 2025 quarters AND declare 'no subsidiary/associate/JV' in their filings. Fill-only
(con index3 must be currently None; std index1 present). con_announce_date = std_announce_date.
Writes docs/sf_fundamentals.json + scripts/fundamentals.json. Run: python -X utf8 apply_nosub_constd.py
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")
MIRROR = os.path.join(HERE, "fundamentals.json")

COMPANIES = ["AUBANK","BANDHANBNK","CANFINHOME","COLPAL","DATAPATTNS","FIVESTAR","GILLETTE",
             "GRSE","HOMEFIRST","HONAUT","MSUMI","NIVABUPA","NSLNISP","PAGEIND","PFIZER",
             "POWERINDIA","SBICARD","SCHNEIDER","TATAELXSI"]
QES = [20250331, 20250630, 20250930, 20251231]

def apply(path):
    d = json.load(open(path))
    filled = 0; skipped = []
    for sym in COMPANIES:
        rows = d.get(sym)
        if not rows:
            skipped.append((sym, "nosym")); continue
        byqe = {r[0]: r for r in rows}
        for qe in QES:
            r = byqe.get(qe)
            if not r:
                skipped.append((sym, qe, "norow")); continue
            # schema [qe, npStd, std_ann, npCon, con_ann]
            while len(r) < 5: r.append(None)
            if r[1] is None:
                skipped.append((sym, qe, "nostd")); continue
            if r[3] is not None:
                skipped.append((sym, qe, "hascon")); continue
            r[3] = r[1]
            if r[4] is None: r[4] = r[2]
            filled += 1
    json.dump(d, open(path, "w"), separators=(",", ":"))
    return filled, skipped

if __name__ == "__main__":
    f1, s1 = apply(DOCS)
    f2, s2 = apply(MIRROR)
    print("docs filled", f1, "mirror filled", f2)
    if s1: print("skipped(docs):", s1)
