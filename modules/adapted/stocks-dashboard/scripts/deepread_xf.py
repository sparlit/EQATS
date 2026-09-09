import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""Render the CROSS-FILING PDF (_vpdf/SYM_QE_xf.pdf = the qe+1yr filing) for deep-read agents. The TARGET
value is the YEAR-AGO (qe) consolidated column of this filing. Prints stored anchors: current-quarter
(qe+1yr) con/std to verify the current column, and TARGET-quarter (qe) std as the exact year-ago anchor.
Run: python -X utf8 deepread_xf.py SYM QE
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import fitz
import numpy as np
import vp2_crop as V

HERE = os.path.dirname(os.path.abspath(__file__))


def cvl(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe:
            return r[3]
    return None


def svl(s, qe):
    for r in V.data.get(s, []):
        if r[0] == qe:
            return r[1]
    return None


def main():
    sym, q = sys.argv[1], int(sys.argv[2])
    qn = q + 10000
    pdfp = os.path.join(HERE, "_vpdf", "%s_%d_xf.pdf" % (sym, q))
    if not os.path.exists(pdfp):
        print("NO-PDF")
        return
    cprev, ccur = cvl(sym, V.prevq(qn)), cvl(sym, qn)
    doc = fitz.open(pdfp)
    p = V.find_con_pl_page(doc, cprev, ccur)
    if p is None:
        p = V.find_pl_page_by_neighbors(doc, cprev, ccur)
    if p is None:
        p = V.find_con_page(doc)
    out = []
    if p is not None:
        pg = doc[p]
        H = pg.rect.height
        W = pg.rect.width

        def piece(x0, x1, a, b, dpi):
            pm = pg.get_pixmap(dpi=dpi, clip=fitz.Rect(W * x0, H * a, W * x1, H * b))
            im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
            return cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)

        def save(img, suf, Wt=2600):
            img = cv2.resize(img, (Wt, int(img.shape[0] * Wt / img.shape[1])))
            bar = np.full((54, Wt, 3), 30, np.uint8)
            cv2.putText(
                bar,
                "%s read YEAR-AGO(%d) col. cur=%d curCon=%s curStd=%s | TGT(%d) std=%s con=want"
                % (sym, q, qn, ccur, svl(sym, qn), q, svl(sym, q)),
                (8, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.74,
                (255, 255, 255),
                2,
            )
            fn = os.path.join(HERE, "_vp2", "%s_%d_xf%s.png" % (sym, q, suf))
            cv2.imwrite(fn, np.vstack([bar, img]))
            return fn

        out.append(save(piece(0.0, 1.0, 0.05, 0.97, 360), ""))
        L = piece(0.0, 0.30, 0.05, 0.97, 460)
        R = piece(0.45, 1.0, 0.05, 0.97, 460)
        h = min(L.shape[0], R.shape[0])
        sep = np.full((h, 14, 3), 180, np.uint8)
        out.append(save(cv2.hconcat([L[:h], sep, R[:h]]), "_ch", 2800))
    print("PAGE", p, "PAGES", len(doc))
    print(
        "CUR",
        qn,
        "curCon",
        ccur,
        "curStd",
        svl(sym, qn),
        "| TARGET-yago",
        q,
        "tgtStd",
        svl(sym, q),
        "tgtCon(want)",
        cvl(sym, q),
    )
    for f in out:
        print("IMG", f)


if __name__ == "__main__":
    main()
