# -*- coding: utf-8 -*-
"""Verify per-quarter that the filing declares NO subsidiary/associate/JV, so consolidated==standalone
(accounting identity). Reports, per (sym,qe): nosub phrase present?, stored std, stored con. Does NOT
write. Run: python -X utf8 nosub_verify.py
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
HERE = os.path.dirname(os.path.abspath(__file__)); VPDF = os.path.join(HERE, "_vpdf")
FUND = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")

NOSUB = re.compile(r'(company|bank|corporation)\s+(does not have|do not have|has no|have no|did not have)\s+(any\s+)?(a\s+)?subsidiar', re.I)
NOSUB2 = re.compile(r'no\s+subsidiar(y|ies)\s*[/,]\s*(associate|joint|jv)', re.I)

COMPANIES = ["AUBANK","BANDHANBNK","CANFINHOME","COLPAL","DATAPATTNS","FIVESTAR","GILLETTE",
             "GRSE","HOMEFIRST","HONAUT","MSUMI","NIVABUPA","NSLNISP","PAGEIND","PFIZER",
             "POWERINDIA","SBICARD","SCHNEIDER","TATAELXSI"]
QES = [20250331, 20250630, 20250930, 20251231]

def main():
    fund = json.load(open(FUND))
    rep = {}
    for sym in COMPANIES:
        rows = {r[0]: r for r in fund.get(sym, [])}
        comp_has = False
        rep[sym] = []
        for qe in QES:
            srow = rows.get(qe)
            std = srow[1] if srow else None
            con = srow[3] if srow else None
            p = os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe))
            nosub = None
            if os.path.exists(p):
                doc = fitz.open(p); full = " ".join(doc[pi].get_text() for pi in range(len(doc))); doc.close()
                flat = re.sub(r'\s+', ' ', full)
                nosub = bool(NOSUB.search(flat) or NOSUB2.search(flat))
                if nosub: comp_has = True
            rep[sym].append({"qe": qe, "nosub": nosub, "std": std, "con": con, "pdf": os.path.exists(p)})
        rep[sym + "_any_nosub"] = comp_has
    for sym in COMPANIES:
        anyns = rep[sym + "_any_nosub"]
        print("#### %-12s (declares no-sub somewhere: %s)" % (sym, anyns))
        for r in rep[sym]:
            flag = "FILL" if (r["con"] is None and r["std"] is not None) else ("hascon" if r["con"] is not None else "NOSTD")
            print("   %d nosub=%s std=%s con=%s  pdf=%s  -> %s" % (
                r["qe"], r["nosub"], r["std"], r["con"], r["pdf"], flag))
    json.dump(rep, open(os.path.join(HERE, "_nosub_verify.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
