# -*- coding: utf-8 -*-
"""Render the Q4 CROSS-FILING PDF (_vpdf/SYM_QE_q4.pdf = the following-June filing). TARGET = the
PRECEDING-quarter (March, qe) consolidated column. Prints anchors: CURRENT June (qe_june) con/std to
verify the current column, prior-June (year-ago) con for context, and target-March stored std if any.
Run: python -X utf8 deepread_q4.py SYM QE   (QE = the March quarter, e.g. 20200331)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz, cv2, numpy as np, vp2_crop as V

HERE = os.path.dirname(os.path.abspath(__file__))
def cvl(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe: return r[3]
    return None
def svl(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe: return r[1]
    return None

def main():
    sym, q = sys.argv[1], int(sys.argv[2])
    june = (q//10000)*10000 + 630
    pyj = june - 10000
    pdfp = os.path.join(HERE, "_vpdf", "%s_%d_q4.pdf" % (sym, q))
    if not os.path.exists(pdfp): print("NO-PDF"); return
    cjune, cpyj = cvl(sym, june), cvl(sym, pyj)
    doc = fitz.open(pdfp)
    p = V.find_con_pl_page(doc, cjune, cpyj)
    if p is None: p = V.find_pl_page_by_neighbors(doc, cjune, cpyj)
    if p is None: p = V.find_con_page(doc)
    # fallback: any page with 'consolidated' + a profit row + a dense numeric table
    import re as _re
    PFT = _re.compile(r'profit.{0,6}(after tax|for the (period|quarter|year))|profit after tax|net profit|profit/\(loss\)', _re.I)
    DEC = _re.compile(r'\(?-?[\d,]*\d\.\d\d\)?')
    cands = [p] if p is not None else []
    for pp in range(min(len(doc), 50)):
        if pp in cands: continue
        t = doc[pp].get_text(); low = t.lower()
        if "consolidated" in low and PFT.search(low) and len(DEC.findall(t)) >= 8:
            cands.append(pp)
        if len(cands) >= 3: break
    out = []
    for p in cands:
        pg = doc[p]; H = pg.rect.height; W = pg.rect.width
        def piece(x0, x1, a, b, dpi):
            pm = pg.get_pixmap(dpi=dpi, clip=fitz.Rect(W*x0, H*a, W*x1, H*b))
            im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
            return cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
        def save(img, suf, Wt=2800):
            img = cv2.resize(img, (Wt, int(img.shape[0]*Wt/img.shape[1])))
            bar = np.full((54, Wt, 3), 30, np.uint8)
            cv2.putText(bar, "%s read PRECEDING-Q(%d=March) col. cur June=%d curCon=%s curStd=%s | TGT std=%s con=want" % (
                sym, q, june, cjune, svl(sym, june), svl(sym, q)),
                (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
            fn = os.path.join(HERE, "_vp2", "%s_%d_q4%s.png" % (sym, q, suf)); cv2.imwrite(fn, np.vstack([bar, img])); return fn
        out.append(save(piece(0.0, 1.0, 0.05, 0.97, 360), "_p%d" % p))
        L = piece(0.0, 0.30, 0.05, 0.97, 460); R = piece(0.40, 1.0, 0.05, 0.97, 460)
        h = min(L.shape[0], R.shape[0]); sep = np.full((h, 14, 3), 180, np.uint8)
        out.append(save(cv2.hconcat([L[:h], sep, R[:h]]), "_p%d_ch" % p, 3000))
    print("PAGES_RENDERED", cands, "TOTPAGES", len(doc))
    print("CUR-June", june, "curCon", cjune, "curStd", svl(sym, june), "| prior-June", pyj, "con", cpyj,
          "| TARGET-March", q, "tgtStd", svl(sym, q), "tgtCon(want)", cvl(sym, q))
    for f in out: print("IMG", f)

if __name__ == "__main__":
    main()
