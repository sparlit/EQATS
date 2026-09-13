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
"""Render EVERY page of a sym+qe filing at 300 DPI (no scoring) so a P&L on a low-OCR-score page
can still be read. Writes _deepgap/<SYM>_<qe>_allpN.png. Run: python render_all.py SYM qe"""
import json
import os
import sys

import bse_text as T
import bse_vision as V
import fitz

SC = json.load(open("bse_scrips.json"))["by_id"]
OUT = "_deepgap"
os.makedirs(OUT, exist_ok=True)
sym = sys.argv[1]
qe = int(sys.argv[2])
code = SC[sym]
o = V.session()
fl = sorted(V.filings(o, code, pages=30, since="20180101"))
atts = [a for ann, a in fl if T.qe_from_ann(ann) == qe]
print("atts", len(atts))
for ai, att in enumerate(atts[:3]):
    pdf = None
    for base in ("AttachHis", "AttachLive"):
        try:
            dd = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if dd[:4] == b"%PDF":
                pdf = dd
                break
        except Exception:
            pass
    if not pdf:
        print("att", ai, "not pdf")
        continue
    doc = fitz.open(stream=pdf, filetype="pdf")
    print("att", ai, "pages", len(doc))
    for p in range(min(len(doc), 16)):
        doc[p].get_pixmap(dpi=300).save(os.path.join(OUT, "%s_%d_a%dp%d.png" % (sym, qe, ai, p)))
