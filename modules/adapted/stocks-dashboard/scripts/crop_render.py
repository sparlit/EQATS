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
"""Re-render the located table page CROPPED to the standalone-P&L region (left portion) at high DPI,
for banks whose results page also crams segment results / a 2nd table alongside (shrinks the digits).
Reads the page index from the existing _deepgap/<SYM>_<qe>.png by re-locating, or just re-renders the
same page cropped. Run: python crop_render.py SYM qe1 qe2 ..."""
import json
import os
import sys

import bse_text as T
import bse_vision as V
import fitz

SC = json.load(open("bse_scrips.json"))["by_id"]
OUT = "_deepgap"
KW = [
    "interest earned",
    "income from operation",
    "total income",
    "operating profit",
    "provision",
    "profit before tax",
    "tax expense",
    "net profit",
    "profit for the period",
    "profit after tax",
    "earnings per",
]


def score(t):
    t = t.lower()
    return sum(1 for k in KW if k in t)


def main():
    sym = sys.argv[1]
    want = [int(x) for x in sys.argv[2:]]
    code = SC[sym]
    o = V.session()
    fl = sorted(V.filings(o, code, pages=30, since="20180101"))
    byq = {}
    for ann, att in fl:
        byq.setdefault(T.qe_from_ann(ann), []).append(att)
    for qe in want:
        best = None
        for att in byq.get(qe, [])[:3]:
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
                continue
            doc = fitz.open(stream=pdf, filetype="pdf")
            for p in range(min(len(doc), 12)):
                txt = doc[p].get_text()
                if len(txt.strip()) < 60:
                    res, _ = V.OCR(doc[p].get_pixmap(dpi=150).tobytes("png"))
                    txt = " ".join(b[1] for b in res) if res else ""
                s = score(txt)
                if s >= 4 and (best is None or s > best[0]):
                    best = (s, pdf, p)
        if not best:
            print("%d: none" % qe, flush=True)
            continue
        s, pdf, p = best
        doc = fitz.open(stream=pdf, filetype="pdf")
        pg = doc[p]
        r = pg.rect
        clip = fitz.Rect(r.x0, r.y0, r.x0 + r.width * 0.62, r.y1)  # left 62% = standalone table
        pg.get_pixmap(dpi=300, clip=clip).save(os.path.join(OUT, "%s_%d.png" % (sym, qe)))
        print("%d: page %d cropped-left @300dpi" % (qe, p), flush=True)


if __name__ == "__main__":
    main()
