# -*- coding: utf-8 -*-
"""Render an NSE insurer result PDF (_vpdf/SYM_QE_nse.pdf) for deep-read. Insurers file IRDAI format
(Policyholders' Revenue A/c + Shareholders' P&L). Net profit = 'Profit/(loss) after tax' in the
Shareholders'/Consolidated statement. SBILIFE & STARHEALTH have NO subsidiaries (std==con) -> read the
standalone PAT and use as con. LICI/HDFCLIFE -> read the CONSOLIDATED PAT. Insurer Q-filings show
[current-Q, year-ago-Q, prior-FY] (and sometimes H1/9M, and a preceding-quarter). Anchor on whichever
comparative column matches a stored value. Prints the FULL stored series. Run: python -X utf8 deepread_nse.py SYM QE
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz, cv2, numpy as np, json

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "..", "docs", "sf_fundamentals.json")))
MONTHS = {1:"january",2:"february",3:"march",4:"april",5:"may",6:"june",7:"july",8:"august",9:"september",10:"october",11:"november",12:"december"}

def qpats(qe):
    y,m,d = qe//10000,(qe//100)%100,qe%100; mn=MONTHS[m]
    return [p.lower() for p in ["%02d/%02d/%d"%(d,m,y),"%02d.%02d.%d"%(d,m,y),"%02d-%02d-%d"%(d,m,y),
            "%s %d, %d"%(mn,d,y),"%d %s %d"%(d,mn,y),"%dth %s %d"%(d,mn,y),"%s %d,%d"%(mn,d,y)]]

def main():
    sym, q = sys.argv[1], int(sys.argv[2])
    pdfp = os.path.join(HERE, "_vpdf", "%s_%d_nse.pdf" % (sym, q))
    if not os.path.exists(pdfp): print("NO-PDF"); return
    doc = fitz.open(pdfp)
    tot = sum(len(doc[p].get_text()) for p in range(len(doc)))
    scanned = tot < 4000
    pats = qpats(q)
    picks = []
    if scanned:
        picks = list(range(min(len(doc), 26)))
    else:
        scored = []
        for p in range(len(doc)):
            t = doc[p].get_text(); low = t.lower()
            nums = len(re.findall(r'\(?-?[\d,]*\d\.\d\d\)?', t))
            if nums < 6: continue
            sc = nums*0.1
            if "consolidated" in low: sc += 5
            if re.search(r'profit.{0,14}(after tax|for the (period|quarter|year))|profit after tax', low): sc += 4
            if re.search(r'shareholder', low): sc += 2
            if any(x in low for x in pats): sc += 3
            scored.append((sc, p))
        scored.sort(reverse=True)
        picks = sorted([p for _, p in scored[:7]])
    out = []
    for p in picks:
        pg = doc[p]; H = pg.rect.height; W = pg.rect.width
        dpi = 150 if scanned else 230
        pm = pg.get_pixmap(dpi=dpi, clip=fitz.Rect(0, H*0.03, W, H*0.99))
        im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
        im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n==3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
        Wt = 2200; im = cv2.resize(im, (Wt, int(im.shape[0]*Wt/im.shape[1])))
        bar = np.full((46, Wt, 3), 30, np.uint8)
        cv2.putText(bar, "%s qe=%d  page %d/%d" % (sym, q, p, len(doc)), (8,32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        fn = os.path.join(HERE, "_vp2", "%s_%d_nse_p%d.png" % (sym, q, p)); cv2.imwrite(fn, np.vstack([bar, im])); out.append(fn)
    print("SCANNED" if scanned else "TEXT", "pages", len(doc), "rendered", picks)
    print("STORED SERIES for", sym, "(qe: std / con):")
    for r in D.get(sym, []):
        print("   %d  std=%s  con=%s" % (r[0], r[1], r[3]))
    for f in out: print("IMG", f)

if __name__ == "__main__":
    main()
