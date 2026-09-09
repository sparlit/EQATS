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
"""Insurer P&L-row cropper (full-effort, general-insurer safe).
Locates the STANDALONE 'profit after tax' table row via the PDF TEXT LAYER (fast; scans 30 pages so it
reaches the P&L Account that general insurers bury behind Revenue-Account schedules), then saves a hi-res
crop of that row for VISION reading (the agent reads the real number, so text-layer column-mixing can't
corrupt the value). Prints a text-layer preview for sanity. Writes _vins/<SYM>_<qe>.png + manifest.json.
  python bse_ins_crop.py GICRE 540755 generalinsurancecorporation --quarters 28 --since 20180101
"""
import json
import os
import re
import sys
import time

import bse_vision as V
import cv2
import fitz
import numpy as np
from bse_text import qe_from_ann

VP = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("VPDIR", "_vins"))
os.makedirs(VP, exist_ok=True)
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?%?$")
PATLAB = re.compile(
    r"(net\s*profit|profit\s*/?\s*\(?\s*loss\s*\)?)\s*(after\s*tax|for\s*the\s*(?:period|quarter|year))", re.IGNORECASE
)
EXCL = re.compile(
    r"before\s*tax|comprehensive|exceptional|operating|segment|per\s*(?:equity\s*)?share|earnings?\s*per|premium|claim|commission|dividend|appropriat",
    re.IGNORECASE,
)
QEND = re.compile(r"ended\s+(?:\d{1,2}(?:st|nd|rd|th)?\s+)?([a-z]+)[,\s]+(\d{4})", re.IGNORECASE)
MON = {
    "january": 3,
    "february": 3,
    "march": 3,
    "april": 6,
    "may": 6,
    "june": 6,
    "july": 9,
    "august": 9,
    "september": 9,
    "october": 12,
    "november": 12,
    "december": 12,
    "jan": 3,
    "feb": 3,
    "mar": 3,
    "apr": 6,
    "jun": 6,
    "jul": 9,
    "aug": 9,
    "sep": 9,
    "sept": 9,
    "oct": 12,
    "nov": 12,
    "dec": 12,
}


def to_val(w):
    try:
        return float(w.replace(",", "").replace("(", "-").replace(")", ""))
    except Exception:
        return None


def detect_unit(low):
    if re.search(r"in\s*lakh|in\s*lac|lakhs", low):
        return "Lakh"
    if re.search(r"in\s*crore|crores", low):
        return "Crore"
    if re.search(r"in\s*million|millions", low):
        return "Million"
    return "?"


def qe_from_text(low):
    for m in QEND.finditer(low):
        mon = m.group(1).lower()
        if mon in MON:
            mm = MON[mon]
            return int(m.group(2)) * 10000 + mm * 100 + (31 if mm in (3, 12) else 30)
    return None


def rows_by_y(pg):
    out = {}
    for x0, y0, x1, y1, w, _b, _l, _n in pg.get_text("words"):
        out.setdefault(round((y0 + y1) / 2 / 3.0), []).append((x0, y0, x1, y1, w))
    return out


def locate(doc):
    """(page, y0, y1, unit, qe, preview_first_value) of best STANDALONE profit-after-tax row, or None."""
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        return None  # scanned, no text layer
    full = " ".join(doc[p].get_text() for p in range(min(len(doc), 14))).lower()
    unit = detect_unit(full)
    qe = qe_from_text(full)
    con = False
    best = None
    for pi in range(min(len(doc), 30)):
        pg = doc[pi]
        low = pg.get_text().lower()
        if re.search(r"consolidated\s+(statement|financial|results|profit|segment)", low):
            con = True
        elif re.search(r"standalone\s+(statement|financial|results|profit|segment)", low):
            con = False
        words = [(x0, y0, x1, y1, w) for x0, y0, x1, y1, w, b, l, n in pg.get_text("words")]
        for cells in rows_by_y(pg).values():
            cells = sorted(cells)
            txt = " ".join(c[4] for c in cells)
            if not PATLAB.search(txt) or EXCL.search(txt):
                continue
            yc = sum((c[1] + c[3]) / 2 for c in cells) / len(cells)
            rh = max(c[3] - c[1] for c in cells)
            labx = max([c[0] for c in cells if re.search(r"[a-z]", c[4], re.IGNORECASE)] or [-1])
            band = []  # numeric cells in a y-band around the label (handles label/number y-misalignment)
            for x0, y0, _x1, y1, w in words:
                if x0 > labx and abs((y0 + y1) / 2 - yc) <= max(rh * 0.9, 5) and NUM.match(w.replace(",", "")):
                    v = to_val(w)
                    if v is not None:
                        band.append((x0, v))
            band.sort()
            nums = [v for _, v in band]
            if len(nums) >= 3 and any(abs(v) >= 10 for v in nums):  # real PAT row (carries a crore-scale value)
                y0 = min(c[1] for c in cells)
                y1 = max(c[3] for c in cells)
                loc = (pi, y0, y1, unit, qe, nums[0])
                if not con:
                    return loc
                if best is None:
                    best = loc
    return best


def main():
    a = sys.argv[1:]
    nq = 28
    since = "20180101"
    if "--quarters" in a:
        i = a.index("--quarters")
        nq = int(a[i + 1])
        a = a[:i] + a[i + 2 :]
    if "--since" in a:
        i = a.index("--since")
        since = a[i + 1]
        a = a[:i] + a[i + 2 :]
    sym, code, expect = a[0], int(a[1]), a[2]
    o = V.session()
    fl = sorted(V.filings(o, code, pages=30, since=since), reverse=True)
    print("%s: %d filings" % (sym, len(fl)), flush=True)
    MF = os.path.join(VP, "manifest.json")
    man = json.load(open(MF)) if os.path.exists(MF) else []
    seen = {m["qe"] for m in man if m["sym"] == sym}
    done = len(seen)
    for ann, att in fl:
        if done >= nq:
            break
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
            print("  ann=%d no-pdf" % ann, flush=True)
            continue
        try:
            doc = fitz.open(stream=pdf, filetype="pdf")
            idt = " ".join(doc[p].get_text() for p in range(min(len(doc), 6))).lower().replace(" ", "")
            if expect not in idt:
                print("  ann=%d ident-miss" % ann, flush=True)
                continue
            loc = locate(doc)
        except Exception as e:
            print("  ann=%d err %s" % (ann, str(e)[:50]), flush=True)
            continue
        if not loc:
            print("  ann=%d no-row" % ann, flush=True)
            continue
        pi, y0, y1, unit, qe, first = loc
        if not qe:
            qe = qe_from_ann(ann)
        if not qe or qe in seen:
            print("  ann=%d qe=%s dup/none" % (ann, qe), flush=True)
            continue
        pg = doc[pi]
        clip = fitz.Rect(pg.rect.x0, max(pg.rect.y0, y0 - 12), pg.rect.x1, min(pg.rect.y1, y1 + 10))
        pix = pg.get_pixmap(dpi=300, clip=clip)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        fn = "%s_%d.png" % (sym, qe)
        cv2.imwrite(os.path.join(VP, fn), img)
        man.append({"sym": sym, "qe": qe, "ann": ann, "unit": unit, "img": fn, "page": pi, "preview": first})
        json.dump(man, open(MF, "w"), indent=0)
        seen.add(qe)
        done += 1
        print("  stored %s ann=%d unit=%s pg=%d preview=%s" % (fn, ann, unit, pi, first), flush=True)
        time.sleep(0.3)
    print("DONE %s: %d crops" % (sym, done), flush=True)


if __name__ == "__main__":
    main()
