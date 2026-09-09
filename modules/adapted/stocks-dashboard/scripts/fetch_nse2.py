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
"""Content-verified NSE re-fetch for wrong-attachment / no-PDF-in-window gaps. Wider window, considers ALL
result-ish attachments, and KEEPS only a PDF that actually contains the TARGET quarter-end date on a
financial-statement page (kills cover letters & wrong-quarter grabs). Prefers a CONSOLIDATED page.
Run: python -X utf8 fetch_nse2.py <listfile.json>   (list = [[SYM,qe],...]). Caches _vpdf/SYM_QE_nse.pdf
"""
import contextlib
import datetime
import json
import os
import re
import sys

import fitz
from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
LOG = os.path.join(HERE, "_fetchnse2_log.json")
MONTHS = {
    1: "january",
    2: "february",
    3: "march",
    4: "april",
    5: "may",
    6: "june",
    7: "july",
    8: "august",
    9: "september",
    10: "october",
    11: "november",
    12: "december",
}
BAD = re.compile(
    r"newspaper|analyst|investor (presentation|meet)|intimation of|transcript|press release|earnings call|trading window|record date|investor presentation",
    re.IGNORECASE,
)
GOOD = re.compile(
    r"financial result|integrated filing|outcome of board|statement of|unaudited|audited result", re.IGNORECASE
)
PFT = re.compile(
    r"profit.{0,14}(after tax|before tax|for the (period|quarter|year))|profit after tax|net profit|profit/\(loss\)|total comprehensive",
    re.IGNORECASE,
)
DEC = re.compile(r"\(?-?[\d,]*\d\.\d\d\)?")


def qpats(qe):
    y, m, d = qe // 10000, (qe // 100) % 100, qe % 100
    mn = MONTHS[m]
    return [
        p.lower()
        for p in [
            "%02d/%02d/%d" % (d, m, y),
            "%02d-%02d-%d" % (d, m, y),
            "%02d.%02d.%d" % (d, m, y),
            "%d/%d/%d" % (d, m, y),
            "%s %d, %d" % (mn, d, y),
            "%s %d,%d" % (mn, d, y),
            "%d %s %d" % (d, mn, y),
            "%dth %s %d" % (d, mn, y),
            "%d %s, %d" % (d, mn, y),
            "%dst %s %d" % (d, mn, y),
            "%02d %s %d" % (d, mn, y),
        ]
    ]


def content_rank(pdf, qe):
    """2 if a CONSOLIDATED financial page carries the target qe date; 1 if a (standalone) financial page
    carries it; 0 otherwise."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return 0
    pats = qpats(qe)
    rank = 0
    for p in range(min(len(doc), 60)):
        t = doc[p].get_text()
        low = t.lower()
        if not any(x in low for x in pats):
            continue
        if not PFT.search(low):
            continue
        if len(DEC.findall(t)) < 8:
            continue
        if "consolidated" in low:
            return 2
        rank = max(rank, 1)
    return rank


def ddmmyyyy(qe, plus):
    y, m = qe // 10000, (qe // 100) % 100
    dt = datetime.date(y, m, 28) + datetime.timedelta(days=plus)
    return "%02d-%02d-%04d" % (dt.day, dt.month, dt.year)


def main():
    refetch = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    s = cr.Session(impersonate="chrome")

    def sget(url, **kw):
        kw.setdefault("timeout", 45)
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
    for sym, qe in refetch:
        key = "%s|%d" % (sym, qe)
        if os.path.exists(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe))):
            log[key] = "got"
            got += 1
            continue
        ref = {"Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"}
        with contextlib.suppress(Exception):
            sget(ref["Referer"])
        lo = ddmmyyyy(qe, 5)
        hi = ddmmyyyy(qe, 400)  # WIDE: catch late filers
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
            if not f.lower().endswith(".pdf"):
                continue
            blob = (str(rec.get("desc", "")) + " " + str(rec.get("attchmntText", ""))).lower()
            if BAD.search(blob):
                continue
            ri = 1 if GOOD.search(blob) else 0
            try:
                sz = float(str(rec.get("attFileSize", "0")).split()[0])
            except:
                sz = 0
            cands.append((ri, sz, rec.get("an_dt", ""), f))
        cands.sort(reverse=True)  # result-ish first, then largest
        best = None
        bestrank = 0
        for ri, sz, dt, f in cands[:10]:
            try:
                r = sget(f, headers=ref, timeout=60)
            except Exception:
                continue
            if r.content[:4] != b"%PDF":
                continue
            rk = content_rank(r.content, qe)
            if rk > bestrank:
                bestrank = rk
                best = (r.content, dt)
            if rk == 2:
                break  # consolidated page with target date — done
        if best and bestrank >= 1:
            open(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe)), "wb").write(best[0])
            print("GOT %-11s %d  rank=%d  %dKB  %s" % (sym, qe, bestrank, len(best[0]) // 1024, best[1]), flush=True)
            log[key] = "got-con" if bestrank == 2 else "got-std"
            got += 1
        else:
            print("MISS %-11s %d  (%d cands)" % (sym, qe, len(cands)), flush=True)
            log[key] = "miss"
        json.dump(log, open(LOG, "w"))
    print("DONE got %d / %d" % (got, len(refetch)), flush=True)


if __name__ == "__main__":
    main()
