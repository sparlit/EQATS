# -*- coding: utf-8 -*-
"""For every cached gap PDF whose con is STILL missing, print (as text) every numeric row on the
best consolidated-P&L page (label + numbers, coordinate-reconstructed). Exact digits, cheap to
read. Pick the profit/owners row by anchoring a sibling column on a known neighbor.
Run: python -X utf8 dump_full_rows.py > _full_rows.txt
"""
import os, re, json, glob
from collections import defaultdict
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
NUM = re.compile(r'^\(?-?[\d,]+\.?\d*\)?$')
NUMTOK = re.compile(r'\(?\d[\d,]*\.?\d*\)?')

def con_missing(sym, qe):
    for r in data.get(sym, []):
        if r[0] == qe: return r[3] is None
    return True

def neighbors(arr, qe):
    p = n = None
    for r in arr:
        if r[3] is None: continue
        if r[0] < qe and (p is None or r[0] > p[0]): p = (r[0], r[3])
        if r[0] > qe and (n is None or r[0] < n[0]): n = (r[0], r[3])
    return (p[1] if p else None), (n[1] if n else None)

def best_page(doc):
    best = (-1, None); con = False
    for p in range(min(len(doc), 28)):
        t = doc[p].get_text(); low = t.lower()
        if "consolidated" in low: con = True
        elif re.search(r'standalone\s+(statement|financial|results|ind)', low) and "consolidated" not in low: con = False
        if not con: continue
        score = 0
        if "total income" in low: score += 3
        if "before tax" in low: score += 3
        if re.search(r'for the (period|year)', low): score += 2
        if "attributable" in low and "owner" in low: score += 4
        if "press release" in low or "industry update" in low: score -= 6
        score += min(len(NUMTOK.findall(t)) / 25.0, 6)
        if score > best[0]: best = (score, p)
    return best[1]

def unit(doc):
    t = " ".join(doc[p].get_text() for p in range(min(len(doc), 8))).lower()
    if re.search(r'in\s+lakh|lakhs|in\s+lac', t): return "/100"
    if re.search(r'in\s+million|millions', t): return "/10"
    if re.search(r'in\s+crore|crores', t): return "/1"
    return "?"

for fn in sorted(glob.glob(os.path.join(HERE, "_vpdf", "*.pdf"))):
    base = os.path.basename(fn)[:-4]; sym, qe = base.rsplit("_", 1); qe = int(qe)
    if not con_missing(sym, qe): continue
    try: doc = fitz.open(fn)
    except Exception: continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        print("=== %s : SCANNED" % base); continue
    cp, cn = neighbors(data.get(sym, []), qe)
    bp = best_page(doc)
    if bp is None: print("=== %s : no-page" % base); continue
    print("=== %s  unit=%s  nbrs=%s/%s  (p%d) ===" % (base, unit(doc), cp, cn, bp + 1))
    rows = defaultdict(list)
    for w in doc[bp].get_text("words"): rows[round(w[1] / 3) * 3].append((w[0], w[4]))
    for y in sorted(rows):
        cells = sorted(rows[y]); label = " ".join(w for _, w in cells if not NUM.match(w.replace(',', '')))
        nums = [w for _, w in cells if NUM.match(w.replace(',', ''))]
        low = label.lower()
        if len(nums) >= 2 and ("profit" in low or "owner" in low or "attributable" in low or "non-controlling" in low or "non controlling" in low):
            print("   %-44s | %s" % (label[:44], " ".join(nums[:5])))
