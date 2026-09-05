# -*- coding: utf-8 -*-
"""Render the best consolidated-P&L page for every cached gap PDF whose con is STILL missing.
Scores pages by numeric density + presence of total-income/profit-before-tax/profit-for-period
in a consolidated context, so it skips press-release/notes/segment pages. Renders top page (+next).
Run: python -X utf8 render_best.py
"""
import os, re, json, glob
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
OUT = os.path.join(HERE, "_vpng2"); os.makedirs(OUT, exist_ok=True)
NUMTOK = re.compile(r'\(?\d[\d,]*\.?\d*\)?')

def con_missing(sym, qe):
    for r in data.get(sym, []):
        if r[0] == qe: return r[3] is None
    return True

def best_page(doc):
    best = (-1, None); con = False
    for p in range(min(len(doc), 28)):
        t = doc[p].get_text(); low = t.lower()
        if re.search(r'consolidated', low): con = True
        elif re.search(r'standalone\s+(statement|financial|results|ind)', low) and "consolidated" not in low: con = False
        if not con: continue
        score = 0
        if "total income" in low: score += 3
        if "profit before tax" in low or "profit/(loss) before tax" in low: score += 3
        if re.search(r'profit\s*/?\s*\(?loss\)?\s*for the (period|year)', low): score += 3
        if "attributable" in low and "owner" in low: score += 4
        if "press release" in low or "industry update" in low: score -= 6
        if "notes" in low and "income" not in low: score -= 3
        score += min(len(NUMTOK.findall(t)) / 25.0, 6)
        if score > best[0]: best = (score, p)
    return best[1]

count = 0
for fn in sorted(glob.glob(os.path.join(HERE, "_vpdf", "*.pdf"))):
    base = os.path.basename(fn)[:-4]; sym, qe = base.rsplit("_", 1); qe = int(qe)
    if not con_missing(sym, qe): continue
    try: doc = fitz.open(fn)
    except Exception: continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        print("%-26s SCANNED" % base); continue
    bp = best_page(doc)
    if bp is None: print("%-26s no-page" % base); continue
    for pp in [bp, bp + 1]:
        if pp < len(doc):
            doc[pp].get_pixmap(dpi=180).save(os.path.join(OUT, "%s_p%d.png" % (base, pp + 1)))
    print("%-26s -> p%d(+%d)" % (base, bp + 1, bp + 2)); count += 1
print("rendered %d" % count)
