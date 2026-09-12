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
"""Backfill PRE-IPO quarters for recent-IPO Nifty500 stocks (missing year-ago bases -> YoY filter
excludes them). For each: fetch result filings via strCat=Result (bypasses buried-results), parse
std/con for col0=current, col1=preceding, col2=year-ago (bse_text.parse_pdf), ann-based quarter
mapping, cross-filing consensus. VALIDATION: only trust a stock if >=1 extracted quarter matches a
stored value (within 2%) -> confirms basis/scale alignment, so we never write misaligned data.
Writes _preipo_extract.json {sym:{"ok":bool,"fills":{qe:[std,con]}}} (does NOT modify data).
Run: python -X utf8 backfill_preipo.py
"""
import json
import os
import re
import statistics
import time
from collections import defaultdict

import bse_text as T
import bse_vision as V

HERE = os.path.dirname(os.path.abspath(__file__))
FUND = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
isin_map = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_isin"]
OUTF = os.path.join(HERE, "_preipo_extract.json")
SYMS = [
    "NSLNISP",
    "MANKIND",
    "PTCIL",
    "LLOYDSME",
    "NETWEB",
    "SBFC",
    "CONCORDBIO",
    "JIOFIN",
    "RRKABEL",
    "JSWINFRA",
    "BLUEJET",
    "HONASA",
    "IREDA",
    "TATATECH",
    "DOMS",
    "JYOTICNC",
    "BHARTIHEXA",
    "AIIL",
    "INDGN",
    "AADHARHFC",
    "TBOTEK",
    "GODIGIT",
    "ABDL",
    "EMCURE",
    "OLAELEC",
    "FIRSTCRY",
    "PREMIERENE",
    "BAJAJHFL",
    "HYUNDAI",
    "WAAREEENER",
    "AFCONS",
    "SAGILITY",
    "ACMESOLAR",
    "SWIGGY",
    "NIVABUPA",
    "NTPCGREEN",
    "SAILIFE",
    "VMM",
    "IKS",
    "IGIL",
    "ONESOURCE",
    "ITCHOTELS",
    "ATHERENERG",
    "BELRISE",
    "AEGISVOPAK",
    "THELEELA",
    "ENRIN",
    "ABLBL",
    "HDBFS",
    "TRAVELFOOD",
    "ANTHEM",
    "CPPLUS",
    "JSWCEMENT",
    "URBANCO",
    "JAINREC",
    "TATACAP",
    "LGEINDIA",
    "CANHLIFE",
    "LENSKART",
    "GROWW",
    "TMCV",
    "PINELABS",
    "EMMVEE",
    "PWL",
    "TENNIND",
    "MEESHO",
    "ICICIAMC",
]


def qe_from_ann(a):
    y, m = a // 10000, (a // 100) % 100
    if 7 <= m <= 9:
        return y * 10000 + 630
    if 10 <= m <= 12:
        return y * 10000 + 930
    if 1 <= m <= 3:
        return (y - 1) * 10000 + 1231
    if 4 <= m <= 6:
        return y * 10000 + 331
    return 0


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


def code_of(sym):
    if sym in scrips:
        return scrips[sym]
    FUND.get(sym)
    return None  # ISIN not in fundamentals; rely on by_id


o = V.session()


def result_filings(code, since):
    out = []
    for pg in range(1, 6):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=Result"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=20261231&strType=C" % (pg, since, code)
        )
        try:
            rows = json.loads(V.get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            ns = (r.get("NEWSSUB") or "") + (r.get("SUBCATNAME") or "")
            if "result" in ns.lower() and r.get("ATTACHMENTNAME"):
                a = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                out.append((int(a) if a else 0, r["ATTACHMENTNAME"]))
        if len(rows) < 50:
            break
    return sorted(set(out))


def fetch(att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            pass
    return None


def stored(sym, qe, idx):
    for r in FUND.get(sym, []):
        if r[0] == qe:
            return r[idx]
    return None


def main():
    out = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    for n, sym in enumerate(SYMS):
        if sym in out:
            continue
        code = code_of(sym)
        if not code:
            out[sym] = {"ok": False, "note": "no-bse-code"}
            print("  %-12s NO-CODE" % sym, flush=True)
            json.dump(out, open(OUTF, "w"))
            continue
        if n and n % 8 == 0:
            time.sleep(2)
            V.session()
        first_q = FUND.get(sym, [[99999999]])[0][0]
        fl = result_filings(code, "%d0101" % (first_q // 10000 - 2))
        accS = defaultdict(list)
        accC = defaultdict(list)
        for ann, att in fl:
            pdf = fetch(att)
            if not pdf:
                continue
            try:
                r = T.parse_pdf(pdf, ann)
            except Exception:
                r = None
            if not r:
                continue
            std_c, con_c, _ = r
            qmap = [qe_from_ann(ann), prevq(qe_from_ann(ann)), qe_from_ann(ann) - 10000]
            for cols, acc in ((std_c, accS), (con_c, accC)):
                if cols:
                    for i, v in enumerate(cols[:3]):
                        if i < len(qmap) and qmap[i]:
                            acc[qmap[i]].append(v)
            time.sleep(0.25)

        def cons(vals):
            best = []
            for v in vals:
                g = [x for x in vals if abs(x - v) <= max(0.5, abs(v) * 0.02)]
                if len(g) > len(best):
                    best = g
            return round(statistics.median(best), 2) if best else None

        serS = {q: cons(v) for q, v in accS.items()}
        serC = {q: cons(v) for q, v in accC.items()}
        # validate: an extracted quarter matches a stored value (std or con) within 2%
        ok = False
        for q in set(list(serS) + list(serC)):
            for ser, idx in ((serS, 1), (serC, 3)):
                sv = stored(sym, q, idx)
                ev = ser.get(q)
                if sv is not None and ev is not None and abs(sv) > 1 and abs(ev - sv) <= abs(sv) * 0.02:
                    ok = True
        # fills = quarters NOT currently stored (pre-IPO / gaps), 2021+
        fills = {}
        for q in sorted(set(list(serS) + list(serC))):
            if q < 20210101:
                continue
            cur_s = stored(sym, q, 1)
            cur_c = stored(sym, q, 3)
            ns = serS.get(q) if cur_s is None else None
            nc = serC.get(q) if cur_c is None else None
            if ns is not None or nc is not None:
                fills[q] = [ns, nc]
        out[sym] = {"ok": ok, "code": code, "filings": len(fl), "fills": fills}
        print("  %-12s ok=%s filings=%d fills=%d %s" % (sym, ok, len(fl), len(fills), sorted(fills)[:4]), flush=True)
        json.dump(out, open(OUTF, "w"))
    json.dump(out, open(OUTF, "w"))
    good = sum(1 for v in out.values() if v.get("ok") and v.get("fills"))
    print("DONE. validated stocks with fills: %d / %d" % (good, len(SYMS)), flush=True)


if __name__ == "__main__":
    main()
