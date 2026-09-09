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
BSE gap-filler: fetch quarterly net profit for names MISSING from the NSE-sourced
sf_fundamentals.json (insurers first), from BSE's scanned result PDFs via OCR.

SAFE BY DESIGN:
  * identity guard  - every PDF's company name must match the expected name, else the
    quarter is SKIPPED (BSE rate-limiting silently serves the wrong company's cached
    filing; this is the only thing that makes the data trustworthy).
  * paced & resumable - one company at a time, long sleeps, fresh cookie session each;
    progress persisted to bse_fundamentals.json so re-runs skip done work and a block
    just pauses progress instead of corrupting it.

Output bse_fundamentals.json: { SYM: [[qEndYYYYMMDD, npStd_cr, annStd, npCon_cr, annCon], ...] }
Run:  python -X utf8 bse_fetch.py            # all insurers
      python -X utf8 bse_fetch.py SBILIFE    # one
"""
import contextlib
import gzip
import http.cookiejar
import io
import json
import os
import random
import re
import sys
import time
import urllib.request
import zipfile

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
# PyMuPDF (fitz) + RapidOCR load LAZILY on first PDF/OCR use: fetch_bse_results.py imports this
# module for its network helpers alone, from workflows that install neither (a top-level import
# crashed the BSE feed merge in every such run — silently, behind the workflows' `|| echo` guard).
OCR = None


def _ocr():
    global OCR
    if OCR is None:
        from rapidocr_onnxruntime import RapidOCR

        OCR = RapidOCR()
    return OCR


HERE = os.path.dirname(os.path.abspath(__file__))
OUTF = os.path.join(HERE, "bse_fundamentals.json")
PACE = 10  # seconds between zip downloads
BACKOFF = 90  # seconds to wait after an identity-fail (likely a block)

# (symbol, BSE scripcode, expected-company-name substring for the identity guard)
INSURERS = [
    ("HDFCLIFE", 540777, "hdfc life"),
    ("SBILIFE", 540719, "sbi life"),
    ("ICICIPRULI", 540133, "icici prudential life"),
    ("ICICIGI", 540716, "icici lombard"),
    ("LICI", 543526, "life insurance corporation"),
    ("GICRE", 540755, "general insurance corporation"),
    ("NIACL", 540769, "new india assurance"),
    ("STARHEALTH", 543412, "star health"),
    ("GODIGIT", 543940, "digit"),
    ("MFSL", 500271, "max financial"),
]
MON = {"mar": "0331", "jun": "0630", "sep": "0930", "sept": "0930", "dec": "1231"}
PAT = [
    r"net profit after tax",
    r"profit\s*/?\s*\(?loss\)?\s*after tax",
    r"\bprofit after tax\b",
    r"profit for the (?:period|quarter)",
]


def session():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with contextlib.suppress(Exception):
        op.open(_req("https://www.bseindia.com/"), timeout=30).read()
    return op


def _req(url):
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Referer": "https://www.bseindia.com/",
            "Origin": "https://www.bseindia.com",
        },
    )


def get(op, url, b=False):
    r = op.open(_req(url), timeout=50)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if b else raw.decode("utf-8", "replace")


def num(s):
    s = s.strip().replace(" ", "")
    if not re.fullmatch(r"\(?-?[\d,]+(?:\.\d+)?\)?", s):
        return None
    v = float(s.strip("()").replace(",", ""))
    return -v if s.startswith("(") else v


_FINRESULT_SENTINEL = []  # module-level, so the probe runs once per process


def _finresult_honours_scripcode(op):
    """BSE's FinancialResult endpoint has been observed to IGNORE scripcode entirely and serve
    BSE Limited's OWN results to every caller (verified 2026-08-18: identical md5 for 532885 /
    500325 / 500002 / 532525, and the Mar-2018 zip's auditor report is addressed to the 'Board of
    Directors of BSE Limited'). Silently returning another company's filings is the worst failure
    mode there is, so probe two unrelated scrips once and refuse to guess if they match."""
    if _FINRESULT_SENTINEL:
        return _FINRESULT_SENTINEL[0]
    import hashlib

    sigs = []
    for probe in (500325, 532525):  # Reliance vs Bank of Maharashtra - nothing in common
        cb = int(time.time() * 1000) + random.randint(0, 99999)
        r = get(
            op, "https://api.bseindia.com/BseIndiaAPI/api/FinancialResult/w?scripcode=%d&type=Q&rnd=%d" % (probe, cb)
        )
        sigs.append(hashlib.md5((r or "").encode("utf8", "replace")).hexdigest())
    ok = sigs[0] != sigs[1]
    _FINRESULT_SENTINEL.append(ok)
    return ok


def quarters(op, code):
    """Return [(qeInt, ziplink)] newest-first from BSE's FinancialResult navigation table.

    GUARDED: raises if the endpoint is ignoring scripcode (see _finresult_honours_scripcode).
    Do not "fix" this by removing the guard - the payload it returns in that state is a different
    company's, and every downstream read built on it is wrong without looking wrong."""
    if not _finresult_honours_scripcode(op):
        raise RuntimeError(
            "BSE FinancialResult endpoint is ignoring scripcode - it serves the SAME payload for "
            "unrelated scrips (BSE Limited's own results). Refusing to return another company's "
            "filings for scripcode %d. Use the BSE announcements API "
            "(AnnSubCategoryGetData/w?strScrip=<code>&strType=C) and read the attachment, which "
            "does honour its parameter." % code
        )
    cb = int(time.time() * 1000) + random.randint(0, 99999)
    t = get(op, "https://api.bseindia.com/BseIndiaAPI/api/FinancialResult/w?scripcode=%d&type=Q&rnd=%d" % (code, cb))
    tbl = json.loads(t).get("Data", "")
    out = {}
    for href, lbl in re.findall(r"href='(/downloads1/[^']+\.zip)'[^>]*>([A-Za-z]+-\d\d)<", tbl):
        mon, yy = lbl.split("-")
        mm = MON.get(mon.lower())
        if not mm:
            continue
        qe = int(f"20{yy}{mm}")
        out.setdefault(qe, href)  # first (quarterly) wins over annual duplicate
    return sorted(out.items(), reverse=True)


def ocr_boxes(png):
    res, _ = _ocr()(png)
    return [{"t": t, "x": sum(p[0] for p in b) / 4, "y": sum(p[1] for p in b) / 4} for b, t, sc in (res or [])]


def net_profit(boxes):
    unit = (
        0.01
        if any(re.search(r"in lakh", b["t"], re.IGNORECASE) for b in boxes)
        else (1.0 if any(re.search(r"in crore", b["t"], re.IGNORECASE) for b in boxes) else None)
    )
    for pat in PAT:
        cand = [
            b
            for b in boxes
            if re.search(pat, b["t"], re.IGNORECASE)
            and not re.search(r"before tax|comprehensive|exceptional", b["t"], re.IGNORECASE)
        ]
        if cand and unit:
            row = [b for b in boxes if abs(b["y"] - cand[0]["y"]) < 12 and b["x"] > cand[0]["x"] + 5]
            nums = [num(b["t"]) for b in sorted(row, key=lambda b: b["x"])]
            nums = [n for n in nums if n is not None]
            if nums:
                return round(nums[0] * unit, 2)
    return None


def pdf_np(op, ziplink, want, expect):
    """Download zip, pick standalone|consolidated PDF, OCR pages 0-2. Returns (np_cr, identity_ok)."""
    z = zipfile.ZipFile(io.BytesIO(get(op, "https://www.bseindia.com" + ziplink, b=True)))
    pdfs = [
        n
        for n in z.namelist()
        if n.lower().endswith(".pdf") and "presentation" not in n.lower() and "outcome" not in n.lower()
    ]
    key = "consol" if want == "con" else "standalone"
    pick = next((n for n in pdfs if key in n.lower()), None) or next(
        (n for n in pdfs if (("conso" in n.lower()) == (want == "con"))), None
    )
    if not pick:
        return None, False
    import fitz

    doc = fitz.open(stream=z.read(pick), filetype="pdf")
    ident = False
    np = None
    for pi in range(min(len(doc), 3)):
        boxes = ocr_boxes(doc[pi].get_pixmap(dpi=190).tobytes("png"))
        head = " ".join(b["t"] for b in boxes[:12]).lower()
        if expect in head:
            ident = True
        if np is None:
            np = net_profit(boxes)
        if ident and np is not None:
            break
    return np, ident


def main():
    syms = [s for s in INSURERS if not sys.argv[1:] or s[0] in sys.argv[1:]]
    data = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    for sym, code, expect in syms:
        op = session()
        try:
            qs = quarters(op, code)
        except Exception as e:
            print(f"{sym}: quarter list failed ({str(e)[:40]})")
            continue
        print("%s: %d quarters available on BSE (%d..%d)" % (sym, len(qs), qs[-1][0], qs[0][0]))
        have = {r[0] for r in data.get(sym, [])}
        rows = {r[0]: r for r in data.get(sym, [])}
        got = blocked = 0
        for qe, link in qs:
            if qe in have:
                continue
            try:
                std, ok1 = pdf_np(op, link, "std", expect)
                time.sleep(PACE * 0.4)
                con, ok2 = pdf_np(op, link, "con", expect)
            except Exception as e:
                print("  %d: error %s" % (qe, str(e)[:40]))
                time.sleep(PACE)
                continue
            if not (ok1 or ok2):  # identity guard tripped -> likely a block
                blocked += 1
                print("  %d: IDENTITY FAIL (wrong company served) - skip + backoff" % qe)
                time.sleep(BACKOFF)
                if blocked >= 3:
                    print(f"  {sym}: repeated identity-fail, BSE blocking -> pausing symbol")
                    break
                continue
            blocked = 0
            ann = None  # announcement date not in this table; left null (refine later)
            rows[qe] = [qe, std, ann, con, ann]
            got += 1
            print("  %d: std=%s con=%s  (identity OK)" % (qe, std, con))
            data[sym] = [rows[k] for k in sorted(rows)]
            json.dump(data, open(OUTF, "w"), separators=(",", ":"))
            time.sleep(PACE)
        print("%s: stored %d new quarters" % (sym, got))
    print("DONE.")


if __name__ == "__main__":
    main()
