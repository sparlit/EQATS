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
"""Direct-vision BSE backfill. For each results filing, crop the net-profit TABLE ROW from BOTH the
standalone and the consolidated P&L (>=3 numeric columns; OCR only locates, vision reads the digits).
Quarter inferred from the filing date. The agent reads the first number (current quarter) x unit.

  python bse_pages.py MCX 534091 multicommodity --quarters 8 --since 20220101
Saves _vp/pages/<SYM>_<qe>_std.png and _<qe>_con.png + _vp/pages/<SYM>.json
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

OCR = V.OCR
OUT = os.path.join(V.VP, "pages")
os.makedirs(OUT, exist_ok=True)
ISNUM = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?$")
CON_HDR = re.compile(r"consolidated\s+(statement|financial|results|segment|unaudited|audited|profit)", re.IGNORECASE)
STD_HDR = re.compile(
    r"(standalone|unconsolidated)\s+(statement|financial|results|segment|unaudited|audited|profit)", re.IGNORECASE
)


def qe_from_ann(ann):
    y, m = ann // 10000, (ann // 100) % 100
    if 7 <= m <= 9:
        return y * 10000 + 630
    if 10 <= m <= 12:
        return y * 10000 + 930
    if 1 <= m <= 3:
        return (y - 1) * 10000 + 1231
    if 4 <= m <= 6:
        return y * 10000 + 331
    return 0


def row_crop(pg, c, pm):
    H = pg.rect.height
    ry = c["y"] / pm.height * H
    clip = fitz.Rect(pg.rect.x0, ry - H * 0.05, pg.rect.x1, ry + H * 0.03)
    pix = pg.get_pixmap(dpi=300, clip=clip)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)


def crop_both(pdf, expect, ann):
    """Return (qe, unit, ident, std_img, con_img). Statement context is sticky across pages
    (the 'Consolidated...' / 'Standalone...' heading often sits a page above the table)."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    unit = "?"
    ident = False
    con_ctx = False
    std = con = None
    for pi in range(min(len(doc), 22)):
        pg = doc[pi]
        pm = pg.get_pixmap(dpi=160)
        try:
            res, _ = OCR(pm.tobytes("png"))
        except Exception:
            continue
        if not res:
            continue
        boxes = [{"t": t, "x": sum(p[0] for p in b) / 4, "y": sum(p[1] for p in b) / 4} for b, t, sc in res]
        flat = " ".join(b["t"] for b in boxes).lower()
        flatns = flat.replace(" ", "")
        if expect in flatns:
            ident = True
        if unit == "?":
            if re.search(r"in\s*lakh|in\s*lac|\blacs?\b", flat):
                unit = "Lakh"
            elif re.search(r"in\s*crore", flat):
                unit = "Crore"
        if CON_HDR.search(flat):
            con_ctx = True
        elif STD_HDR.search(flat):
            con_ctx = False
        # first real net-profit row on this page
        rowimg = None
        for pat in V.PAT:
            for c in [
                b
                for b in boxes
                if re.search(pat, b["t"], re.IGNORECASE)
                and not re.search(r"before tax|comprehensive|exceptional|operating", b["t"], re.IGNORECASE)
            ]:
                if (
                    len(
                        [
                            b
                            for b in boxes
                            if abs(b["y"] - c["y"]) < 14 and b["x"] > c["x"] + 5 and ISNUM.match(b["t"].strip())
                        ]
                    )
                    >= 3
                ):
                    rowimg = row_crop(pg, c, pm)
                    break
            if rowimg is not None:
                break
        if rowimg is None:
            continue
        if con_ctx and con is None:
            con = rowimg
        elif not con_ctx and std is None:
            std = rowimg
        if std is not None and con is not None:
            break
    return qe_from_ann(ann), unit, ident, std, con


def main():
    a = sys.argv[1:]
    nq = 8
    since = "20220101"
    if "--quarters" in a:
        i = a.index("--quarters")
        nq = int(a[i + 1])
        a = a[:i] + a[i + 2 :]
    if "--since" in a:
        i = a.index("--since")
        since = a[i + 1]
        a = a[:i] + a[i + 2 :]
    sym, code, expect = a[0], int(a[1]), a[2].lower()
    o = V.session()
    fl = V.filings(o, code, since=since)
    print("%s: %d result filings" % (sym, len(fl)), flush=True)
    idx = []
    seen = set()
    for ann, att in fl:
        if len(seen) >= nq:
            break
        pdf = None
        for base in ("AttachHis", "AttachLive"):
            try:
                d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
                if d[:4] == b"%PDF":
                    pdf = d
                    break
            except Exception:
                continue
        if not pdf:
            continue
        try:
            loc = V.watchdog(crop_both, 160, pdf, expect, ann)
        except Exception:
            loc = None
        time.sleep(4)
        if not loc:
            continue
        qe, unit, ident, std, con = loc
        if not qe or qe in seen or not ident:
            continue
        seen.add(qe)
        rec = {"sym": sym, "qe": qe, "unit": unit, "std": None, "con": None}
        for tag, img in (("std", std), ("con", con)):
            if img is not None:
                fn = "%s_%d_%s.png" % (sym, qe, tag)
                cv2.imwrite(
                    os.path.join(OUT, fn),
                    V.label_strip(img, "%s  qe=%d  %s  unit=%s  (filed %d)" % (sym, qe, tag.upper(), unit, ann)),
                )
                rec[tag] = fn
        idx.append(rec)
        print("  qe=%d std=%s con=%s" % (qe, rec["std"] is not None, rec["con"] is not None), flush=True)
    json.dump(idx, open(os.path.join(OUT, f"{sym}.json"), "w"), indent=0)
    print("DONE %s: %d quarters" % (sym, len(idx)), flush=True)


if __name__ == "__main__":
    main()
