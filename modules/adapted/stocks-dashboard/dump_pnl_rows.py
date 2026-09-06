# -*- coding: utf-8 -*-
"""For every cached gap PDF in _vpdf/, dump the CONSOLIDATED profit rows (owners-attributable +
profit-for-the-period) with coordinate-reconstructed numbers and the detected unit, so the values
can be read/picked from compact TEXT instead of full-page images. col0 = current quarter.
Run: python -X utf8 dump_pnl_rows.py > _pnl_dump.txt
"""
import os, re, json, glob
from collections import defaultdict
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
NUM = re.compile(r'^\(?-?[\d,]+\.?\d*\)?$')
OWN = re.compile(r'(owners|equity holders) of', re.I)
PFT = re.compile(r'profit\s*/?\s*\(?\s*loss\)?\s*(after tax\s*)?(for|of)\s*the\s*(period|year|quarter)', re.I)
NETP = re.compile(r'net\s+profit', re.I)

def unit_of(doc):
    t = " ".join(doc[p].get_text() for p in range(min(len(doc), 8))).lower()
    if re.search(r'in\s+lakh|in\s+lac|lakhs|in\s+lacs', t): return "lakh(/100)"
    if re.search(r'in\s+million|millions|in\s+mn', t): return "million(/10)"
    if re.search(r'in\s+crore|crores|in\s+cr\b|rs\.?\s*in\s+cr', t): return "crore(/1)"
    return "?"

def rownums(cells):
    return [w for x, w in sorted(cells) if NUM.match(w.replace(',', ''))]

def neighbors(arr, qe):
    p = n = None
    for r in arr:
        if r[3] is None: continue
        if r[0] < qe and (p is None or r[0] > p[0]): p = (r[0], r[3])
        if r[0] > qe and (n is None or r[0] < n[0]): n = (r[0], r[3])
    return (p[1] if p else None), (n[1] if n else None)

for fn in sorted(glob.glob(os.path.join(HERE, "_vpdf", "*.pdf"))):
    base = os.path.basename(fn)[:-4]
    sym, qe = base.rsplit("_", 1); qe = int(qe)
    try:
        doc = fitz.open(fn)
    except Exception:
        print("=== %s %d : OPEN-FAIL" % (sym, qe)); continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        print("=== %s %d : SCANNED (no text) ===" % (sym, qe)); continue
    cp, cn = neighbors(data.get(sym, []), qe)
    print("=== %s %d  unit=%s  neighbors=%s/%s ===" % (sym, qe, unit_of(doc), cp, cn))
    con = False
    for p in range(min(len(doc), 26)):
        low = doc[p].get_text().lower()
        if re.search(r'consolidated\s+(statement|financial|results|segment|un|ind|audited)', low): con = True
        elif re.search(r'standalone\s+(statement|financial|results|segment|un|ind|audited)', low): con = False
        if not con: continue
        rows = defaultdict(list)
        for w in doc[p].get_text("words"): rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            txt = " ".join(w for _, w in sorted(rows[y])); l = txt.lower()
            if "before" in l or "comprehensive" in l or "segment" in l: continue
            if OWN.search(l) or PFT.search(l) or (NETP.search(l) and "for" in l):
                nums = rownums(rows[y])
                if nums:
                    tag = "OWN" if OWN.search(l) else "PFT"
                    print("   p%d %s | %s" % (p + 1, tag, " ".join(nums[:6])))
