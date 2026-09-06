# -*- coding: utf-8 -*-
"""Render the consolidated-P&L STATEMENT page (not cover/notes/segment) for every remaining
con-basis gap with a text PDF. Stricter scoring: require revenue/interest + tax + profit rows;
penalize covers, press releases, notes, segment pages. Renders the top page; for filings with a
separate consolidated statement, also the 2nd distinct high-scoring page. Run after gaps recompute.
Run: python -X utf8 render_pnl2.py
"""
import os, re, json, glob
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
OUT = os.path.join(HERE, "_vpng3"); os.makedirs(OUT, exist_ok=True)
NUMTOK = re.compile(r'\(?\d[\d,]*\.?\d*\)?')
Q = {3: 0, 6: 1, 9: 2, 12: 3}; INV = {v: k for k, v in Q.items()}
DEFUNCT = {'DHFL', 'HDFC', 'ROLTA', 'JPINFRATEC', 'TATAMTRDVR', 'CONSOFINVT', 'UJJIVAN', 'EROSMEDIA', 'UNITECH', 'GVPIL', 'CYIENT', 'IDEA'}

def qi(qe):
    m = (qe // 100) % 100
    return None if m not in Q else (qe // 10000) * 4 + Q[m]
def qefrom(idx): y, q = idx // 4, idx % 4; mo = INV[q]; return y * 10000 + mo * 100 + (31 if mo in (3, 12) else 30)

def gaps():
    idx = json.load(open(os.path.join(HERE, "indices_history.json")))["Nifty 500"]; M = set()
    for x in idx: M.update(x["symbols"])
    out = []
    for s in sorted(M):
        a = data.get(s)
        if not a or not any(r[3] is not None for r in a): continue
        cv = {r[0]: r[3] for r in a}; sq = sorted(set(r[0] for r in a if (r[0] // 100) % 100 in Q and r[0] >= 20200101))
        for i in range(len(sq) - 1):
            x, y = sq[i], sq[i + 1]; ia, ib = qi(x), qi(y)
            if ib - ia - 1 < 1 or ib - ia - 1 >= 3: continue
            ca, cb = cv.get(x), cv.get(y)
            if ca is not None and cb is not None and (abs(ca) >= 15 or abs(cb) >= 15):
                for k in range(ia + 1, ib): out.append((s, qefrom(k)))
    return out

def score(t):
    low = t.lower(); s = 0
    if re.search(r'revenue from operations|interest earned|total income', low): s += 5
    if re.search(r'tax expense|current tax|total tax expense|provision for tax', low) or ("tax" in low and "profit" in low): s += 4
    if re.search(r'profit\s*/?\s*\(?loss\)?\s*for the (period|year)', low): s += 4
    if "attributable" in low and "owner" in low: s += 4
    if re.search(r'earnings per (equity )?share|basic.*diluted', low): s += 2
    if re.search(r'dear sir|board of directors|intimation|enclosed|outcome of', low): s -= 8
    if "press release" in low or "industry update" in low: s -= 6
    if re.search(r'segment (revenue|result|assets|information)', low): s -= 5
    if re.search(r'notes\b|accompanying notes', low) and "income" not in low: s -= 3
    n = len(NUMTOK.findall(t)); s += min(n / 25.0, 6)
    if n < 20: s -= 5
    return s

count = 0
for s, qe in gaps():
    if s in DEFUNCT: continue
    fn = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (s, qe))
    if not os.path.exists(fn): continue
    try: doc = fitz.open(fn)
    except Exception: continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200: continue
    scored = sorted(((score(doc[p].get_text()), p) for p in range(min(len(doc), 26))), reverse=True)
    pages = [scored[0][1]]
    for sc, p in scored[1:4]:
        if sc > scored[0][0] - 3 and abs(p - pages[0]) >= 2: pages.append(p); break
    for p in pages:
        doc[p].get_pixmap(dpi=200).save(os.path.join(OUT, "%s_%d_p%d.png" % (s, qe, p + 1)))
    print("%s_%d -> %s" % (s, qe, [p + 1 for p in pages])); count += 1
print("rendered %d" % count)
