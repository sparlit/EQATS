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
"""Render the standalone-P&L page of a bank's BSE results filings to PNG for direct vision reading
(used when the text layer is scanned/garbled so OCR-locate fails). Renders page 1-2 (where the
quarterly results table sits) at high DPI. Run: python render_deepgap.py SYM qe1 qe2 ..."""
import json
import os
import sys

import bse_text as T
import bse_vision as V
import fitz

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
            print("%d: no-pdf" % qe, flush=True)
            continue
        doc = fitz.open(stream=pdf, filetype="pdf")
        for p in range(min(2, len(doc))):
            pix = doc[p].get_pixmap(dpi=200)
            fn = os.path.join(OUT, "%s_%d_p%d.png" % (sym, qe, p))
            pix.save(fn)
        done.add(qe)
        print("%d: rendered %d pages (pdf %d pp)" % (qe, min(2, len(doc)), len(doc)), flush=True)
    print("rendered:", sorted(done), flush=True)


if __name__ == "__main__":
    main()
