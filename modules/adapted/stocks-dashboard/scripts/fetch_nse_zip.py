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
"""ZIP-aware NSE result fetch. Old NSE filings (≈2019) attach results as .zip archives (SEANN_*.zip), not
PDFs — earlier fetchers required .pdf and skipped them. This downloads the result attachment (zip OR pdf)
mapped to the target quarter, extracts PDFs from zips, scores them (prefers a CONSOLIDATED page), and saves
the best to _vpdf/SYM_QE_nse.pdf. Run: python -X utf8 fetch_nse_zip.py <listfile.json>
"""
import contextlib
import datetime
import io
import json
import os
import re
import sys
import zipfile

import fitz
from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
LOG = os.path.join(HERE, "_fetchzip_log.json")
MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
GOOD = re.compile(r"financial result|integrated filing|outcome of board|audited financial|statement of", re.IGNORECASE)
BAD = re.compile(
    r"newspaper|analyst|investor (presentation|meet)|intimation of|transcript|earnings call|trading window|record date|presentation|press release",
    re.IGNORECASE,
)
CONS = re.compile(r"consolidat", re.IGNORECASE)
PFT = re.compile(r"profit.{0,14}(after tax|for the (period|quarter|year))|profit after tax|net profit", re.IGNORECASE)


def parse_an(dt):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", dt)
    return (MON[m.group(2).lower()], int(m.group(3))) if m else None


def qe_from_ann(mo, y):
    if 7 <= mo <= 9:
        return y * 10000 + 630
    if 10 <= mo <= 12:
        return y * 10000 + 930
    if 1 <= mo <= 3:
        return (y - 1) * 10000 + 1231
    return y * 10000 + 331


def ddmmyyyy(qe, plus):
    y, m = qe // 10000, (qe // 100) % 100
    dt = datetime.date(y, m, 28) + datetime.timedelta(days=plus)
    return "%02d-%02d-%04d" % (dt.day, dt.month, dt.year)


def extract_pdfs(content, name):
    if content[:4] == b"%PDF":
        return [(name, content)]
    if content[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(content))
            out = []
            for n in z.namelist():
                if n.lower().endswith(".pdf"):
                    b = z.read(n)
                    if b[:4] == b"%PDF":
                        out.append((n, b))
            return out
        except Exception:
            return []
    return []


def score(b):
    try:
        doc = fitz.open(stream=b, filetype="pdf")
    except Exception:
        return -1
    sc = 0
    for p in range(min(len(doc), 60)):
        low = doc[p].get_text().lower()
        if "consolidated" in low and PFT.search(low):
            sc += 5
    return sc + len(b) / 2e6


def main():
    targets = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    s = cr.Session(impersonate="chrome")

    def sget(url, **kw):
        kw.setdefault("timeout", 60)
        for a in range(3):
            try:
                return s.get(url, **kw)
            except Exception:
                if a == 2:
                    raise
                import time as _t

                _t.sleep(3)
        return None

    sget("https://www.nseindia.com/")
    got = 0
    for t in targets:
        sym, qe = t["sym"], t["qe"]
        key = "%s|%d" % (sym, qe)
        ref = {"Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"}
        with contextlib.suppress(Exception):
            sget(ref["Referer"])
        lo = ddmmyyyy(qe, 5)
        hi = ddmmyyyy(qe, 200)
        url = (
            f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}"
            f"&from_date={lo}&to_date={hi}"
        )
        try:
            j = sget(url, headers=ref).json()
        except Exception as e:
            print("ERR", key, e, flush=True)
            log[key] = "err"
            continue
        cands = []
        for rec in j:
            f = rec.get("attchmntFile", "")
            if not (f.lower().endswith(".pdf") or f.lower().endswith(".zip")):
                continue
            blob = str(rec.get("desc", "")) + " " + str(rec.get("attchmntText", ""))
            if not GOOD.search(blob) or BAD.search(blob):
                continue
            pa = parse_an(rec.get("an_dt", ""))
            if not pa or qe_from_ann(*pa) != qe:
                continue
            fr = 2 if re.search(r"financial result|audited financial", blob, re.IGNORECASE) else 1
            cands.append((fr, rec.get("an_dt", ""), f))
        cands.sort(reverse=True)
        best = None
        bestsc = 0
        for fr, dt, f in cands[:4]:
            try:
                r = sget(f, headers=ref)
            except Exception:
                continue
            for _nm, b in extract_pdfs(r.content, f):
                sc = score(b)
                if sc > bestsc:
                    bestsc = sc
                    best = (b, dt)
            if best and bestsc >= 5:
                break  # have a consolidated PDF
        if best:
            open(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe)), "wb").write(best[0])
            print("GOT %-11s %d  sc=%.1f %dKB %s" % (sym, qe, bestsc, len(best[0]) // 1024, best[1]), flush=True)
            log[key] = "got" if bestsc >= 5 else "got-nocon"
            got += 1
        else:
            print("MISS %-11s %d (%d cands)" % (sym, qe, len(cands)), flush=True)
            log[key] = "miss"
        json.dump(log, open(LOG, "w"))
    print("DONE got %d / %d" % (got, len(targets)), flush=True)


if __name__ == "__main__":
    main()
