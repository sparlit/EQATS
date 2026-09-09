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
"""Fetch fy_end-March AUDITED results PDF from BSE (curl_cffi) for reconstruction candidates. Saves
_vpdf/SYM_<fyendMar>_bse.pdf. Run: python -X utf8 bse_fetch_fy.py <listfile.json>  (list=[[SYM,fyendMar],...])
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
LOG = os.path.join(HERE, "_bsefy_log.json")


def main():
    targets = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    s = cr.Session(impersonate="chrome")

    def sget(u, **k):
        k.setdefault("timeout", 45)
        k.setdefault("headers", {"Referer": "https://www.bseindia.com/"})
        for a in range(3):
            try:
                return s.get(u, **k)
            except Exception:
                if a == 2:
                    raise
                time.sleep(3)
        return None

    sget("https://www.bseindia.com/")
    got = 0
    for sym, fy in targets:
        key = "%s|%d" % (sym, fy)
        cp = os.path.join(VPDF, "%s_%d_bse.pdf" % (sym, fy))
        if os.path.exists(cp):
            log[key] = "got"
            got += 1
            continue
        code = C.scrips.get(sym)
        if not code:
            print("nocode", sym, flush=True)
            log[key] = "nocode"
            continue
        y = fy // 10000
        lo = "%d0401" % y
        hi = "%d0815" % y  # Q4/annual announced Apr-Aug of fy_end
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=Result"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C" % (lo, code, hi)
        )
        try:
            rows = sget(url).json().get("Table", [])
        except Exception as e:
            print("ERR list", sym, e, flush=True)
            log[key] = "err"
            continue
        cands = []
        for r in rows:
            sub = (r.get("NEWSSUB", "") or "").lower()
            att = r.get("ATTACHMENTNAME", "")
            if not att.lower().endswith(".pdf"):
                continue
            if not any(k in sub for k in ["result", "audited", "financial"]):
                continue
            if any(b in sub for b in ["newspaper", "investor", "analyst", "intimation", "presentation"]):
                continue
            # prefer "year ended" / consolidated / audited
            sc = ("year ended" in sub) + ("consolidat" in sub) + ("audited" in sub)
            try:
                fsz = float(str(r.get("Fld_Attachsize", "0")) or 0)
            except:
                fsz = 0
            cands.append((sc, fsz, r.get("NEWS_DT", ""), att))
        cands.sort(reverse=True)
        best = None
        for sc, fsz, _dt, att in cands[:4]:
            for base in ("AttachHis", "AttachLive"):
                try:
                    d = sget(f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}")
                    if d.content[:4] == b"%PDF":
                        best = d.content
                        break
                except Exception:
                    pass
            if best:
                break
            time.sleep(1)
        if best:
            open(cp, "wb").write(best)
            log[key] = "got"
            got += 1
            print("GOT", key, len(best) // 1024, "KB", flush=True)
        else:
            log[key] = "miss"
            print("MISS", key, "(%d cands)" % len(cands), flush=True)
        json.dump(log, open(LOG, "w"))
        time.sleep(0.5)
    print("DONE got %d / %d" % (got, len(targets)), flush=True)


if __name__ == "__main__":
    main()
