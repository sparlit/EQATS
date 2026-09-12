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
"""Download NSE result PDFs WITHOUT a text-content filter (for SCANNED filings that have no text layer, so
fetch_nse2's text check fails). Maps each result attachment to its quarter via the announcement month, and
prefers an attachment whose description mentions 'consolidated' (banks file a separate consolidated PDF),
else the largest result-ish PDF. Saves _vpdf/SYM_QE_nse.pdf (overwrites). Then vision-read with
deepread_nse.py. Run: python -X utf8 fetch_nse_scan.py <listfile.json>
"""
import contextlib
import datetime
import json
import os
import re
import sys

from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
LOG = os.path.join(HERE, "_fetchscan_log.json")
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
GOOD = re.compile(
    r"financial result|integrated filing|outcome of board|statement of (un)?audited|audited financial", re.IGNORECASE
)
BAD = re.compile(
    r"newspaper|analyst|investor (presentation|meet)|intimation of|transcript|press release|earnings call|trading window|record date|presentation",
    re.IGNORECASE,
)
CONS = re.compile(r"consolidat", re.IGNORECASE)


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


def main():
    targets = json.load(open(sys.argv[1]))
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
            if not f.lower().endswith(".pdf"):
                continue
            blob = str(rec.get("desc", "")) + " " + str(rec.get("attchmntText", ""))
            if not GOOD.search(blob) or BAD.search(blob):
                continue
            pa = parse_an(rec.get("an_dt", ""))
            if not pa or qe_from_ann(*pa) != qe:
                continue
            try:
                sz = float(str(rec.get("attFileSize", "0")).split()[0])
            except:
                sz = 0
            score = (10 if CONS.search(blob) else 0) + min(sz / 500.0, 5)
            cands.append((score, sz, rec.get("an_dt", ""), f))
        cands.sort(reverse=True)
        saved = False
        for score, sz, dt, f in cands[:3]:
            try:
                r = sget(f, headers=ref, timeout=60)
            except Exception:
                continue
            if r.content[:4] == b"%PDF":
                open(os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe)), "wb").write(r.content)
                print("GOT %-11s %d  score=%.1f %dKB  %s" % (sym, qe, score, len(r.content) // 1024, dt), flush=True)
                log[key] = "got"
                got += 1
                saved = True
                break
        if not saved:
            print("MISS %-11s %d  (%d cands)" % (sym, qe, len(cands)), flush=True)
            log[key] = "miss"
        json.dump(log, open(LOG, "w"))
    print("DONE got %d / %d" % (got, len(targets)), flush=True)


if __name__ == "__main__":
    main()
