# -*- coding: utf-8 -*-
"""Anchor-by-search: for each remaining con-basis gap, search the BSE PDF text for the KNOWN
prev-quarter (or year-ago) consolidated value in its likely printed forms (crore as-is, lakh
x100, million x10, with/without commas). When found in a profit/owners row, print that
coordinate-row so col0 (current/gap quarter) can be read directly. Layout-independent.
Run: python -X utf8 search_anchor.py > _search_anchor.txt
"""
import os, re, json
from collections import defaultdict
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
NUM = re.compile(r'^\(?-?[\d,]+\.?\d*\)?$')
Q = {3: 0, 6: 1, 9: 2, 12: 3}; INV = {v: k for k, v in Q.items()}
DEFUNCT = {'DHFL', 'HDFC', 'ROLTA', 'JPINFRATEC', 'TATAMTRDVR', 'CONSOFINVT', 'UJJIVAN', 'EROSMEDIA', 'UNITECH', 'GVPIL', 'CYIENT', 'IDEA'}

def qi(qe):
    m = (qe // 100) % 100
    return None if m not in Q else (qe // 10000) * 4 + Q[m]
def qefrom(idx): y, q = idx // 4, idx % 4; mo = INV[q]; return y * 10000 + mo * 100 + (31 if mo in (3, 12) else 30)
def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)
def cv(s, q):
    for r in data.get(s, []):
        if r[0] == q: return r[3]
    return None

def gaps():
    idx = json.load(open(os.path.join(HERE, "indices_history.json")))["Nifty 500"]; M = set()
    for x in idx: M.update(x["symbols"])
    out = []
    for s in sorted(M):
        a = data.get(s)
        if not a or not any(r[3] is not None for r in a): continue
        cvm = {r[0]: r[3] for r in a}; sq = sorted(set(r[0] for r in a if (r[0] // 100) % 100 in Q and r[0] >= 20200101))
        for i in range(len(sq) - 1):
            x, y = sq[i], sq[i + 1]; ia, ib = qi(x), qi(y)
            if ib - ia - 1 < 1 or ib - ia - 1 >= 3: continue
            ca, cb = cvm.get(x), cvm.get(y)
            if ca is not None and cb is not None and (abs(ca) >= 15 or abs(cb) >= 15):
                for k in range(ia + 1, ib): out.append((s, qefrom(k)))
    return out

def forms(v):
    """printed representations of crore value v across units."""
    out = set()
    for scaled in (v, v * 100, v * 10):
        a = abs(scaled)
        for dec in (2, 1, 0):
            x = ("%.*f" % (dec, a))
            # with indian commas
            ip, _, fp = x.partition(".")
            grp = ip[-3:]; rest = ip[:-3]
            while len(rest) > 2: grp = rest[-2:] + "," + grp; rest = rest[:-2]
            if rest: grp = rest + "," + grp
            out.add(x); out.add(grp + ("." + fp if fp else ""))
    return {o for o in out if len(o.replace(',', '').replace('.', '')) >= 3}

for s, qe in gaps():
    if s in DEFUNCT: continue
    fn = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (s, qe))
    if not os.path.exists(fn): continue
    try: doc = fitz.open(fn)
    except Exception: continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200: continue
    pv = cv(s, prevq(qe)); yv = cv(s, qe - 10000)
    anchors = {}
    if pv is not None: anchors["prev=%s" % pv] = forms(pv)
    if yv is not None: anchors["yago=%s" % yv] = forms(yv)
    print("=== %s %d  (prev=%s yago=%s) ===" % (s, qe, pv, yv))
    found = False
    for p in range(min(len(doc), 26)):
        rows = defaultdict(list)
        for w in doc[p].get_text("words"): rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            cells = sorted(rows[y]); toks = [w for _, w in cells]
            nums = [w for w in toks if NUM.match(w.replace(',', ''))]
            label = " ".join(w for w in toks if not NUM.match(w.replace(',', '')))
            joined = " ".join(nums)
            for desc, fs in anchors.items():
                if any(f in joined for f in fs) and len(nums) >= 2 and ("profit" in label.lower() or "owner" in label.lower() or "loss" in label.lower() or len(label) < 4):
                    print("   p%d [%s] %-34s | %s" % (p + 1, desc, label[:34], " ".join(nums[:5])))
                    found = True
                    break
    if not found: print("   (neighbor value not found in any profit row)")
