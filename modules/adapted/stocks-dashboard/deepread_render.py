# -*- coding: utf-8 -*-
"""Render one stock-quarter's CONSOLIDATED P&L for deep-read agents. Renders a full-page crop AND a
label+consolidated-right-half crop (for side-by-side filings) at high DPI, and prints the stored
neighbors so the agent can anchor to the exact row. Run:  python -X utf8 deepread_render.py SYM QE
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz, cv2, numpy as np, vp2_crop as V

HERE = os.path.dirname(os.path.abspath(__file__))
def conval(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe: return r[3]
    return None
def stdval(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe: return r[1]
    return None

def main():
    sym, q = sys.argv[1], int(sys.argv[2])
    pdfp = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (sym, q))
    if not os.path.exists(pdfp): print("NO-PDF"); return
    cprev, cyago = conval(sym, V.prevq(q)), conval(sym, q - 10000)
    doc = fitz.open(pdfp)
    p = V.find_con_pl_page(doc, cprev, cyago)
    if p is None: p = V.find_pl_page_by_neighbors(doc, cprev, cyago)
    if p is None: p = V.find_con_page(doc)
    out = []
    if p is not None:
        pg = doc[p]; H = pg.rect.height; W = pg.rect.width
        def piece(x0, x1, a, b, dpi):
            pm = pg.get_pixmap(dpi=dpi, clip=fitz.Rect(W*x0, H*a, W*x1, H*b))
            im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
            return cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
        def save(img, suf, Wt=2400):
            img = cv2.resize(img, (Wt, int(img.shape[0]*Wt/img.shape[1])))
            bar = np.full((54, Wt, 3), 30, np.uint8)
            cv2.putText(bar, "%s Qend=%d p%d  prev(%d)con=%s yago(%d)con=%s std=%s" % (
                sym, q, p, V.prevq(q), cprev, q-10000, cyago, stdval(sym, q)),
                (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255,255,255), 2)
            fn = os.path.join(HERE, "_vp2", "%s_%d%s.png" % (sym, q, suf)); cv2.imwrite(fn, np.vstack([bar, img])); return fn
        out.append(save(piece(0.0, 1.0, 0.06, 0.96, 360), ""))                      # full page
        L = piece(0.0, 0.32, 0.06, 0.96, 460); R = piece(0.50, 1.0, 0.06, 0.96, 460)
        h = min(L.shape[0], R.shape[0]); sep = np.full((h, 14, 3), 180, np.uint8)
        out.append(save(cv2.hconcat([L[:h], sep, R[:h]]), "_ch", 2600))             # label + consolidated half
    print("PAGE", p, "PAGES", len(doc))
    print("PREV", V.prevq(q), cprev, "YAGO", q-10000, cyago, "STD", stdval(sym, q))
    for f in out: print("IMG", f)

if __name__ == "__main__":
    main()
