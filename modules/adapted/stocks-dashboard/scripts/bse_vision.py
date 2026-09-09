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
"""
BSE gap-filler, VISION edition. OCR is used only to LOCATE the net-profit row on the
scanned result PDF; the actual number is read by Claude vision from a high-res crop
(OCR mangles digits in these scans). Fetches via the announcements route (not rate-
limited, and carries the point-in-time announcement date).

Stage 1 (this script): for each symbol, pull recent 'Financial Results' filings, download
the PDF, find the STANDALONE P&L page + 'profit after tax' row, verify the company name
(identity guard), read the 'quarter ended' date, and save a labelled high-res crop of that
row. Crops are tiled ~6 per composite for efficient vision reading. Writes _vp/manifest.json.

Stage 2 (the agent): read each composite, take the FIRST number on each row (= current
quarter) x the Lakh/Crore unit, and write bse_fundamentals.json.

Run: python -X utf8 bse_vision.py SBILIFE HDFCLIFE ICICIGI --quarters 4
"""
import concurrent.futures
import contextlib
import gzip
import http.cookiejar
import io
import json
import os
import re
import socket
import sys
import time
import urllib.request

import cv2
import fitz
import numpy as np
from rapidocr_onnxruntime import RapidOCR

socket.setdefaulttimeout(40)  # network guard: a stalled BSE read can't hang the run forever
_WEX = [None]


def watchdog(fn, secs, *a):
    """Run fn(*a) with a hard wall-clock timeout; abandon the worker thread if it hangs (Windows-safe)."""
    if _WEX[0] is None:
        _WEX[0] = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = _WEX[0].submit(fn, *a)
    try:
        return fut.result(timeout=secs)
    except concurrent.futures.TimeoutError:
        _WEX[0].shutdown(wait=False)
        _WEX[0] = None  # drop the stuck thread, fresh executor next call
        msg = "watchdog"
        raise TimeoutError(msg)


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
OCR = RapidOCR()
HERE = os.path.dirname(os.path.abspath(__file__))
VP = os.path.join(HERE, os.environ.get("VPDIR", "_vp"))
os.makedirs(VP, exist_ok=True)
PACE = 4

INS = {  # symbol: (scripcode, expected-name-substring (spaces stripped))
    "HDFCLIFE": (540777, "hdfclife"),
    "SBILIFE": (540719, "sbilife"),
    "ICICIPRULI": (540133, "iciciprudential"),
    "ICICIGI": (540716, "icicilombard"),
    "LICI": (543526, "lifeinsurancecorporation"),
    "GICRE": (540755, "generalinsurancecorporation"),
    "NIACL": (540769, "newindiaassurance"),
    "STARHEALTH": (543412, "starhealth"),
    "GODIGIT": (544179, "digit"),
    "NIVABUPA": (544286, "nivabupa"),
}
MON = {
    "january": "0331?",
    "march": "0331",
    "june": "0630",
    "september": "0930",
    "december": "1231",
    "jan": "0331?",
    "mar": "0331",
    "jun": "0630",
    "sep": "0930",
    "sept": "0930",
    "dec": "1231",
}
PAT = [
    r"net profit after tax",
    r"profit\s*/?\s*\(?loss\)?\s*after tax",
    r"\bprofit after tax\b",
    r"profit for the (?:period|quarter)",
]


def session():
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with contextlib.suppress(Exception):
        o.open(urllib.request.Request("https://www.bseindia.com/", headers={"User-Agent": UA}), timeout=30).read()
    return o


def get(o, u, b=False):
    r = o.open(
        urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}), timeout=60
    )
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if b else raw.decode("utf-8", "replace")


def is_result(r):
    sub = (r.get("SUBCATNAME", "") or "").lower()
    ns = (r.get("NEWSSUB", "") or "").lower()
    if any(
        x in ns
        for x in (
            "xbrl",
            "investor",
            "press release",
            "presentation",
            "earnings call",
            "transcript",
            "intimation",
            "newspaper",
            "analyst",
        )
    ):
        return False
    return (
        "financial result" in sub
        or "financial result" in ns
        or bool(re.search(r"(audited|unaudited).*financial result", ns))
    )


def filings(o, code, pages=12, since="20230101"):
    """Result filings [(ann_int, attachment)] newest-first. Paginates deep (prolific filers
    bury results among many announcements) and matches results by subcat OR headline."""
    out = []
    for pg in range(1, pages + 1):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=20261231&strType=C" % (pg, since, code)
        )
        try:
            rows = json.loads(get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            if is_result(r) and r.get("ATTACHMENTNAME"):
                ann = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                out.append((int(ann) if ann else 0, r["ATTACHMENTNAME"]))
        if len(rows) < 50:
            break
        time.sleep(1)
    return out


def qe_from(text):
    m = re.search(r"ended\s+([a-z]+)\s*\d{1,2},?\s*(\d{4})", text)
    if not m:
        return None
    mm = MON.get(m.group(1))
    if not mm or "?" in mm:
        return None
    return int(m.group(2) + mm)


ISNUM = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?$")


def locate(pdf, expect):
    """Find the STANDALONE P&L table row for net profit. Identity is checked across all early
    pages (sticky), so a P&L page without the company name isn't falsely rejected. The matched
    row must have >=3 numeric columns (a real table row) so prose/press-release pages that merely
    contain the phrase 'profit after tax' are skipped. Returns (qe, unit, ident, crop_bgr) or None."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    ident = False
    unit = "?"
    result = None
    for pi in range(min(len(doc), 14)):
        pg = doc[pi]
        pm = pg.get_pixmap(dpi=170)
        res, _ = OCR(pm.tobytes("png"))
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
        if result is None and not ("consolidated" in flat and "standalone" not in flat):
            for pat in PAT:
                for c in [
                    b
                    for b in boxes
                    if re.search(pat, b["t"], re.IGNORECASE)
                    and not re.search(r"before tax|comprehensive|exceptional|operating", b["t"], re.IGNORECASE)
                ]:
                    rownums = [
                        b
                        for b in boxes
                        if abs(b["y"] - c["y"]) < 14 and b["x"] > c["x"] + 5 and ISNUM.match(b["t"].strip())
                    ]
                    if len(rownums) >= 3:  # real table row, not prose
                        qe = qe_from(flat)
                        if qe:
                            H = pg.rect.height
                            ry = c["y"] / pm.height * H
                            clip = fitz.Rect(pg.rect.x0, ry - H * 0.045, pg.rect.x1, ry + H * 0.028)
                            pix = pg.get_pixmap(dpi=300, clip=clip)
                            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
                            img = (
                                cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                                if pix.n == 3
                                else cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                            )
                            result = (qe, img)
                        break
                if result:
                    break
        if ident and result:
            break
    if result is None:
        return None
    return result[0], unit, ident, result[1]


def label_strip(img, text):
    img = cv2.resize(img, (1700, int(img.shape[0] * 1700 / img.shape[1])))
    bar = np.full((46, 1700, 3), 30, np.uint8)
    cv2.putText(bar, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return np.vstack([bar, img, np.full((6, 1700, 3), 200, np.uint8)])


def main():
    args = sys.argv[1:]
    nq = 4
    tfile = None
    since = "20230101"
    if "--quarters" in args:
        i = args.index("--quarters")
        nq = int(args[i + 1])
        args = args[:i] + args[i + 2 :]
    if "--targets" in args:
        i = args.index("--targets")
        tfile = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if "--since" in args:
        i = args.index("--since")
        since = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if tfile:  # [[sym, scripcode, expect_token], ...]
        targets = [(t[0], int(t[1]), t[2]) for t in json.load(open(tfile))]
    else:
        syms = [s for s in args if s in INS] or list(INS)
        targets = [(s, INS[s][0], INS[s][1]) for s in syms]

    def fetch_one(o, att, expect):
        pdf = None
        for base in ("AttachHis", "AttachLive"):
            try:
                d = get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
                if d[:4] == b"%PDF":
                    pdf = d
                    break
            except Exception:
                continue
        return locate(pdf, expect) if pdf else None

    MF = os.path.join(VP, "manifest.json")
    manifest = json.load(open(MF)) if os.path.exists(MF) else []
    BSEF = os.path.join(HERE, "bse_fundamentals.json")
    recorded = json.load(open(BSEF)) if os.path.exists(BSEF) else {}
    for sym, code, expect in targets:
        crops = [
            f
            for f in os.listdir(VP)
            if f.startswith(sym + "_") and f.endswith(".png") and "batch" not in f and "salv" not in f
        ]
        if len(crops) >= nq or len(recorded.get(sym, [])) >= nq:
            print("%s: already done (%d crops / %d recorded) — skip" % (sym, len(crops), len(recorded.get(sym, []))))
            continue
        try:
            o = session()
            fl = filings(o, code, since=since)
        except Exception as e:
            print(f"{sym}: filings failed {str(e)[:40]}")
            continue
        print("%s: %d result filings found" % (sym, len(fl)))
        seen = {int(re.search(r"_(\d+)\.png$", f).group(1)) for f in crops if re.search(r"_(\d+)\.png$", f)}
        done = len(seen)
        for ann, att in fl:
            if done >= nq:
                break
            try:
                loc = watchdog(fetch_one, 150, o, att, expect)  # hard 150s cap — no infinite hangs
            except Exception as e:
                print("  ann=%d timeout/err %s" % (ann, str(e)[:30]))
                continue
            time.sleep(PACE)
            if not loc:
                continue
            qe, unit, ident, img = loc
            if not qe or qe in seen or not ident:
                print("  ann=%d skip (qe=%s ident=%s)" % (ann, qe, ident))
                continue
            m2 = ((qe // 100) % 100) + 2
            y2 = qe // 10000 + (1 if m2 > 12 else 0)
            approx = y2 * 10000 + ((m2 - 12) if m2 > 12 else m2) * 100 + 15
            ann = ann if (ann and qe + 18 <= ann <= qe + 130) else approx
            seen.add(qe)
            done += 1
            fn = "%s_%d.png" % (sym, qe)
            cv2.imwrite(os.path.join(VP, fn), img)
            manifest.append({"sym": sym, "qe": qe, "ann": ann, "unit": unit, "img": fn})
            json.dump(manifest, open(MF, "w"), indent=0)  # incremental: survives a kill
            print("  stored crop %s (ann=%d unit=%s)" % (fn, ann, unit))
    print("DONE. manifest has %d crops total." % len(manifest))


if __name__ == "__main__":
    main()
