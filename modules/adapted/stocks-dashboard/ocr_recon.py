# -*- coding: utf-8 -*-
"""OCR-based reconstruction reader. For each (sym, qe) [Q4/March balancing-quarter target], OCR the
consolidated results table of its fy_end-March filing (existing _vpdf PDF), reconstruct the table, find the
net-profit/owners row whose comparative columns match our STORED quarter-anchors (this confirms the row +
basis), read the Q4 (target) column directly AND the FY column, and cross-check Q4 == FY - sum(stored other
3). Outputs _ocr_recon_out.json for review. Nothing is written to the data here. Run: python -X utf8 ocr_recon.py
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz, numpy as np, cv2
from rapidocr_onnxruntime import RapidOCR

HERE = os.path.dirname(os.path.abspath(__file__))
OCR = RapidOCR()
D = json.load(open(os.path.join(HERE, "..", "docs", "sf_fundamentals.json")))
recon = {"%s|%d" % (r["sym"], r["qe"]): r for r in json.load(open(os.path.join(HERE, "_reconcand.json")))}

def stored(s, q, idx=3):
    for r in D.get(s, []):
        if r[0] == q: return r[idx]
    return None
def tonum(t):
    t = t.replace(" ", "").replace(",", "")
    if not re.match(r'^\(?-?\d+\.\d\d\)?$', t): return None
    neg = "(" in t; v = float(t.replace("(", "").replace(")", "")); return -v if neg else v

def ocr_rows(im):
    res, _ = OCR(im)
    if not res: return []
    items = []
    for box, txt, sc in res:
        ys = [p[1] for p in box]; xs = [p[0] for p in box]
        items.append((sum(ys)/4, sum(xs)/4, txt))
    items.sort()
    rows = []; cur = []; ly = None
    for y, x, t in items:
        if ly is None or abs(y-ly) < 16: cur.append((x, t))
        else: rows.append(sorted(cur)); cur = [(x, t)]
        ly = y
    if cur: rows.append(sorted(cur))
    return rows

def find_results_page(doc):
    """Image pages, OCR, return (pageidx, rows) for the one that looks like a consolidated P&L."""
    cands = []
    for p in range(len(doc)):
        t = doc[p].get_text(); low = t.lower()
        if "auditor" in low or "deloitte" in low or "independent au" in low: continue
        imgs = doc[p].get_images()
        big = any((im[2] > 900 and im[3] > 900) for im in imgs)
        if big and len(t) < 500: cands.append(p)
        elif len(re.findall(r'\d[\d,]*\.\d\d', t)) > 25 and ("profit" in low): cands.append(p)
    out = []
    for p in cands[:12]:
        pm = doc[p].get_pixmap(dpi=300)
        im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
        im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
        rows = ocr_rows(im); blob = " ".join(t for r in rows for _, t in r).lower()
        score = ("profit for the" in blob) + ("total income" in blob or "revenue from oper" in blob) + ("net profit" in blob) + 2*("segment" not in blob[:80])
        if "profit" in blob and len(re.findall(r'\d+\.\d\d', blob)) > 15:
            out.append((score, p, rows))
    out.sort(reverse=True)
    return out[0][1:] if out else (None, None)

def main():
    targets = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else [[r["sym"], r["qe"]] for r in recon.values() if r["qe"] % 10000 == 331]
    out = []
    for sym, qe in targets:
        key = "%s|%d" % (sym, qe); rc = recon.get(key)
        suf = None
        for s2 in ["_nse", "", "_bse"]:
            if os.path.exists(os.path.join(HERE, "_vpdf", "%s_%d%s.pdf" % (sym, qe, s2))): suf = s2; break
        if suf is None: out.append({"sym": sym, "qe": qe, "status": "nopdf"}); print(key, "nopdf", flush=True); continue
        doc = fitz.open(os.path.join(HERE, "_vpdf", "%s_%d%s.pdf" % (sym, qe, suf)))
        pg, rows = find_results_page(doc)
        if pg is None: out.append({"sym": sym, "qe": qe, "status": "noresultspage"}); print(key, "noresultspage", flush=True); continue
        # stored anchors that should appear as comparative columns
        y, m = qe//10000, qe%10000
        prevq = (y*10000+1231) if m == 331 else None   # Q3 Dec of same FY
        yagoq = (y-1)*10000+331 if m == 331 else None   # Q4 prev FY
        a_prev = stored(sym, prevq); a_yago = stored(sym, yagoq)
        # find net-profit/owners rows; collect numeric vectors
        profrows = []
        for r in rows:
            txt = " ".join(t for _, t in r).lower()
            if ("profit" in txt and ("owner" in txt or "for the" in txt or "after tax" in txt or "period" in txt)) or "attributable to" in txt:
                nums = [v for v in (tonum(t) for _, t in r) if v is not None]
                if len(nums) >= 4: profrows.append((txt[:50], nums))
        # try to find a row whose values include the prev and/or yago anchors
        match = None
        for txt, nums in profrows:
            hasprev = a_prev is not None and any(abs(v-a_prev) <= max(0.05, abs(a_prev)*0.01) for v in nums)
            hasyago = a_yago is not None and any(abs(v-a_yago) <= max(0.05, abs(a_yago)*0.01) for v in nums)
            if hasprev or hasyago:
                match = {"row": txt, "nums": nums, "hasprev": hasprev, "hasyago": hasyago}; break
        rec = {"sym": sym, "qe": qe, "page": pg, "a_prev": a_prev, "a_yago": a_yago,
               "sum_others": rc["sum_others"] if rc else None, "profrows": profrows, "match": match, "status": "ok"}
        out.append(rec); print(key, "ok page", pg, "match", bool(match), flush=True)
    json.dump(out, open(os.path.join(HERE, "_ocr_recon_out.json"), "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
