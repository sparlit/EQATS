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
"""Fetch NSE financial-result PDFs for the NSE-only insurer gaps (BSE has no filing; NSE 403-blocks plain
urllib). Uses curl_cffi (chrome TLS impersonation) to defeat Akamai. For each (symbol, target quarter) it
queries NSE corporate-announcements in the announcement window, keeps financial-result filings, and
downloads the largest candidate PDF to _vpdf/SYM_QE_nse.pdf. Run: python -X utf8 fetch_nse.py
"""
import datetime
import json
import os
import re
import sys

from curl_cffi import requests as cr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
os.makedirs(VPDF, exist_ok=True)

TARGETS = {
    "LICI": [20230630, 20250331, 20250630],
    "SBILIFE": [20230930],
    "STARHEALTH": [20220630, 20220930, 20230630, 20250930],
    "HDFCLIFE": [20200331, 20200630],
}
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
GOOD = re.compile(r"financial result|integrated filing|outcome of board", re.IGNORECASE)
BAD = re.compile(
    r"newspaper|analyst|investor (presentation|meet)|intimation|schedule|transcript|press release", re.IGNORECASE
)


def ddmmyyyy(qe, plus):
    y, m, _d = qe // 10000, (qe // 100) % 100, qe % 100
    dt = datetime.date(y, m, 28) + datetime.timedelta(days=plus)
    return "%02d-%02d-%04d" % (dt.day, dt.month, dt.year)


def parse_an(dt):
    # "10-Aug-2023 18:07:44" -> (month, year)
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", dt)
    if not m:
        return None
    return MON[m.group(2).lower()], int(m.group(3))


def qe_from_ann(mo, y):
    if 7 <= mo <= 9:
        return y * 10000 + 630  # Q1 announced Jul-Sep
    if 10 <= mo <= 12:
        return y * 10000 + 930  # Q2 announced Oct-Dec
    if 1 <= mo <= 3:
        return (y - 1) * 10000 + 1231  # Q3 announced Jan-Mar
    return y * 10000 + 331  # Q4 announced Apr-Jun


import contextlib

import fitz


def con_score(pdf):
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return -1
    sc = 0
    for p in range(min(len(doc), 60)):
        low = doc[p].get_text().lower()
        if "consolidated" in low and re.search(r"profit.{0,12}(after tax|for the (period|quarter|year))", low):
            sc += 1
    return sc


def main():
    global TARGETS
    if len(sys.argv) > 1:
        flat = json.load(open(sys.argv[1]))
        TARGETS = {}
        for s, q in flat:
            TARGETS.setdefault(s, []).append(q)
    s = cr.Session(impersonate="chrome")

    def sget(url, **kw):
        kw.setdefault("timeout", 45)
        for attempt in range(3):
            try:
                return s.get(url, **kw)
            except Exception:
                if attempt == 2:
                    raise
                import time as _t

                _t.sleep(3)
        return None

    sget("https://www.nseindia.com/")
    log = (
        json.load(open(os.path.join(HERE, "_fetchnse_log.json")))
        if os.path.exists(os.path.join(HERE, "_fetchnse_log.json"))
        else {}
    )
    import time as _t

    for sym, qes in TARGETS.items():
        ref = {"Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"}
        with contextlib.suppress(Exception):
            sget(ref["Referer"])
        for qe in qes:
            if os.path.exists(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe))):
                log["%s|%d" % (sym, qe)] = "got"
                continue  # already fetched
            lo = ddmmyyyy(qe, 5)
            hi = ddmmyyyy(qe, 170)
            url = (
                f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}"
                f"&from_date={lo}&to_date={hi}"
            )
            try:
                j = sget(url, headers=ref).json()
            except Exception as e:
                print("ERR list", sym, qe, e)
                log["%s|%d" % (sym, qe)] = "err"
                continue
            cands = []
            for rec in j:
                desc = str(rec.get("desc", ""))
                blob = desc + " " + str(rec.get("attchmntText", ""))
                # GOOD may be signalled by the subject OR the attachment text, but only the
                # announcement SUBJECT (desc) may VETO via BAD. Genuine results filings routinely
                # mention "press release"/etc. in attchmntText ("...along with press release"),
                # which must not drop the real results PDF (e.g. TIINDIA QE 20220630).
                if not GOOD.search(blob) or BAD.search(desc):
                    continue
                f = rec.get("attchmntFile", "")
                if not f.lower().endswith(".pdf"):
                    continue
                pa = parse_an(rec.get("an_dt", ""))
                if not pa or qe_from_ann(*pa) != qe:
                    continue  # MUST map to the target quarter
                try:
                    sz = float(str(rec.get("attFileSize", "0")).split()[0])
                except:
                    sz = 0
                cands.append((sz, rec.get("an_dt", ""), f))
            cands.sort(reverse=True)
            best = None
            bestsc = (-1, -1)
            for sz, dt, f in cands[:6]:
                try:
                    r = sget(f, headers=ref, timeout=60)
                    if r.content[:4] != b"%PDF":
                        continue
                    sc = con_score(r.content)
                    if (sc, len(r.content)) > bestsc:
                        bestsc = (sc, len(r.content))
                        best = (r.content, dt, sc)
                except Exception:
                    pass
            if best:
                open(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe)), "wb").write(best[0])
                print("GOT %-11s %d  conpages=%d  %dKB  %s" % (sym, qe, best[2], len(best[0]) // 1024, best[1]))
                log["%s|%d" % (sym, qe)] = "got"
            else:
                print("MISS %-11s %d  (%d cands mapped)" % (sym, qe, len(cands)))
                log["%s|%d" % (sym, qe)] = "miss"
    json.dump(log, open(os.path.join(HERE, "_fetchnse_log.json"), "w"))
    print("DONE", sum(1 for v in log.values() if v == "got"), "/", sum(len(v) for v in TARGETS.values()))


if __name__ == "__main__":
    main()
