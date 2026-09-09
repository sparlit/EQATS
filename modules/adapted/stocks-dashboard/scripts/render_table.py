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
"""For each wanted quarter, fetch the BSE results PDF and render the page MOST LIKELY to be the
standalone results table — detected by rendering each page's text-OR-image and scoring for the
results-table signature. For scanned PDFs we render every page 1..6 at 200dpi and pick by simple
heuristic isn't possible without OCR, so we render pages 1-4 and stack the 2 middle ones (where the
bank P&L table usually sits) into one composite per quarter for a single vision read.
Run: python render_table.py SYM qe1 qe2 ..."""
import json
import os
import sys

import bse_text as T
import bse_vision as V
import cv2
import fitz
import numpy as np

SC = json.load(open("bse_scrips.json"))["by_id"]
OUT = "_deepgap"
os.makedirs(OUT, exist_ok=True)


def main():
    sym = sys.argv[1]
    want = {int(x) for x in sys.argv[2:]}
    code = SC[sym]
    o = V.session()
    fl = sorted(V.filings(o, code, pages=30, since="20180101"))
    done = set()
    for ann, att in fl:
        qe = T.qe_from_ann(ann)
        if qe not in want or qe in done:
            continue
        pdf = None
        for base in ("AttachHis", "AttachLive"):
            try:
                d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
                if d[:4] == b"%PDF":
                    pdf = d
                    break
            except Exception:
                pass
        if not pdf:
            print("%d no-pdf" % qe, flush=True)
            continue
        doc = fitz.open(stream=pdf, filetype="pdf")
        n = len(doc)
        # render pages 1..min(4,n-1) stacked into one composite (skip cover p0)
        imgs = []
        for p in range(1, min(5, n)):
            pix = doc[p].get_pixmap(dpi=150)
            im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
            im = cv2.resize(im, (1100, int(im.shape[0] * 1100 / im.shape[1])))
            bar = np.full((26, 1100, 3), 20, np.uint8)
            cv2.putText(bar, "%s %d page %d" % (sym, qe, p), (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            imgs.append(np.vstack([bar, im, np.full((3, 1100, 3), 120, np.uint8)]))
        if imgs:
            cv2.imwrite(os.path.join(OUT, "%s_%d_tbl.png" % (sym, qe)), np.vstack(imgs))
            done.add(qe)
            print("%d composite of %d pages (pdf %dpp)" % (qe, len(imgs), n), flush=True)
    print("done:", sorted(done), flush=True)


if __name__ == "__main__":
    main()
