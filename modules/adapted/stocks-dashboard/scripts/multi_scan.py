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
"""Like deep_scan but renders the TOP-N scoring pages (not just best) so the real P&L can be
found even when an annexure/ratios page out-scores it. Writes _deepgap/<SYM>_<qe>_pN.png.
Run: python -X utf8 multi_scan.py SYM qe1 qe2 ..."""
import json
import os
import sys

import bse_text as T
import bse_vision as V
import fitz

SC = json.load(open("bse_scrips.json"))["by_id"]
OUT = "_deepgap"
os.makedirs(OUT, exist_ok=True)
KW = [
    "interest earned",
    "income from operation",
    "revenue from operation",
    "total income",
    "operating profit",
    "provision",
    "profit before tax",
    "exceptional",
    "tax expense",
    "net profit",
    "profit for the period",
    "profit after tax",
    "earnings per",
    "total expenditure",
    "operating expenses",
    "total expenses",
]


def score(txt):
    t = txt.lower()
    return sum(1 for k in KW if k in t)


def main():
    sym = sys.argv[1]
    want = [int(x) for x in sys.argv[2:]]
    code = SC[sym]
    o = V.session()
    fl = sorted(V.filings(o, code, pages=30, since="20180101"))
    byq = {}
    for ann, att in fl:
        qe = T.qe_from_ann(ann)
        byq.setdefault(qe, []).append(att)
    for qe in want:
        atts = byq.get(qe, [])
        cands = []  # (score, pdf, page_no, npp)
        for att in atts[:4]:
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
            for p in range(min(len(doc), 16)):
                pg = doc[p]
                txt = pg.get_text()
                if len(txt.strip()) < 60:
                    res, _ = V.OCR(pg.get_pixmap(dpi=150).tobytes("png"))
                    txt = " ".join(b[1] for b in res) if res else ""
                s = score(txt)
                if s >= 3:
                    cands.append((s, pdf, p, len(doc)))
        cands.sort(key=lambda x: -x[0])
        if not cands:
            print("%d: NONE (atts=%d)" % (qe, len(atts)), flush=True)
            continue
        seen = set()
        for _i, (s, pdf, p, npp) in enumerate(cands[:4]):
            if p in seen:
                continue
            seen.add(p)
            doc = fitz.open(stream=pdf, filetype="pdf")
            fn = "%s_%d_p%d.png" % (sym, qe, p)
            doc[p].get_pixmap(dpi=300).save(os.path.join(OUT, fn))
            print("%d: page %d/%d score=%d -> %s" % (qe, p, npp, s, fn), flush=True)


if __name__ == "__main__":
    main()
