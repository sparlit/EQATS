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
"""OCR the consolidated results table of BSE fy_end-March filings; extract profit/owners rows with their
column values so they can be anchor-matched + used for balancing-quarter reconstruction. Outputs
_ocr_fy_out.json. Run: python -X utf8 ocr_fy.py <listfile.json>  (list=[[SYM,fyendMar],...])
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import fitz
import numpy as np
from rapidocr_onnxruntime import RapidOCR

HERE = os.path.dirname(os.path.abspath(__file__))
OCR = RapidOCR()


def tonum(t):
    t = t.replace(" ", "").replace(",", "")
    if not re.match(r"^\(?-?\d+\.\d\d\)?$", t):
        return None
    neg = "(" in t
    v = float(t.replace("(", "").replace(")", ""))
    return -v if neg else v


def ocr_rows(im):
    res, _ = OCR(im)
    if not res:
        return []
    items = sorted((sum(p[1] for p in b) / 4, sum(p[0] for p in b) / 4, t) for b, t, s in res)
    rows = []
    cur = []
    ly = None
    for y, x, t in items:
        if ly is None or abs(y - ly) < 16:
            cur.append((x, t))
        else:
            rows.append(sorted(cur))
            cur = [(x, t)]
        ly = y
    if cur:
        rows.append(sorted(cur))
    return rows


def main():
    targets = json.load(open(sys.argv[1]))
    out = []
    for sym, fy in targets:
        p = os.path.join(HERE, "_vpdf", "%s_%d_bse.pdf" % (sym, fy))
        if not os.path.exists(p):
            out.append({"sym": sym, "fy": fy, "status": "nopdf"})
            print(sym, fy, "nopdf", flush=True)
            continue
        doc = fitz.open(p)
        # candidate image pages (scanned results), skip auditor
        cands = []
        for pi in range(len(doc)):
            t = doc[pi].get_text()
            low = t.lower()
            if "auditor" in low or "deloitte" in low or "b s r" in low or "independent au" in low:
                continue
            imgs = doc[pi].get_images()
            if (any(im[2] > 800 and im[3] > 800 for im in imgs) and len(t) < 600) or (
                len(re.findall(r"\d[\d,]*\.\d\d", t)) > 25 and "profit" in low
            ):
                cands.append(pi)
        best = None
        for pi in cands[:8]:
            pm = doc[pi].get_pixmap(dpi=300)
            im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
            im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)
            rows = ocr_rows(im)
            blob = " ".join(t for r in rows for _, t in r).lower()
            if "segment" in blob[:120]:
                continue
            prof = []
            for r in rows:
                txt = " ".join(t for _, t in r)
                low = txt.lower()
                if (
                    "profit" in low and ("owner" in low or "for the" in low or "after tax" in low or "period" in low)
                ) or "attributable to" in low:
                    nums = [v for v in (tonum(t) for _, t in r) if v is not None]
                    if len(nums) >= 4:
                        prof.append([txt[:55], nums])
            sc = ("consolidat" in blob) + len(prof) + ("total income" in blob or "revenue from oper" in blob)
            if prof and (best is None or sc > best[0]):
                best = (sc, pi, prof)
        if best:
            out.append({"sym": sym, "fy": fy, "page": best[1], "profrows": best[2], "status": "ok"})
            print(sym, fy, "ok page", best[1], "rows", len(best[2]), flush=True)
        else:
            out.append({"sym": sym, "fy": fy, "status": "noprof"})
            print(sym, fy, "noprof", flush=True)
    json.dump(out, open(os.path.join(HERE, "_ocr_fy_out.json"), "w"), indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
