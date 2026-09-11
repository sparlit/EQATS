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
"""Re-fetch the CORRECT results PDF for priority recoverable gaps and dump its consolidated P&L
rows. For each (sym,qe): list result filings, download every candidate announced 20-130 days after
qe, SCORE each PDF for being the real consolidated P&L (total income/revenue/interest + tax +
profit-for-period + consolidated + numeric density, minus press-release/RPT), keep the best, save
to _vpdf2/, and print the best consolidated-P&L page's profit/owners rows + neighbors for anchoring.
Run: python -X utf8 refetch_verify.py
"""
import datetime
import json
import os
import re
import time
from collections import defaultdict

import bse_vision as V
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
codes = json.load(open(os.path.join(HERE, "_gap_codes.json")))
codes.setdefault("GSPL", 532702)
codes.setdefault("PEL", 500302)
OUT = os.path.join(HERE, "_vpdf2")
os.makedirs(OUT, exist_ok=True)
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
NUMTOK = re.compile(r"\(?\d[\d,]*\.?\d*\)?")
TARGETS = [
    ("CIPLA", 20220630),
    ("SBIN", 20220630),
    ("M&M", 20220630),
    ("ULTRACEMCO", 20220630),
    ("JINDALSTEL", 20220630),
    ("GSPL", 20221231),
    ("OBEROIRLTY", 20220630),
    ("SOLARINDS", 20220630),
    ("EIDPARRY", 20220630),
    ("PIRAMALFIN", 20220630),
    ("CREDITACC", 20220630),
    ("JMFINANCIL", 20220630),
    ("FMGOETZE", 20221231),
    ("JKLAKSHMI", 20220630),
    ("SAPPHIRE", 20220930),
    ("HCC", 20220630),
    ("TATAINVEST", 20220630),
    ("KSB", 20210930),
    ("SUNTECK", 20210331),
    ("SONACOMS", 20210331),
    ("PCBL", 20220630),
    ("HFCL", 20220630),
    ("KKCL", 20220630),
    ("PARAGMILK", 20211231),
    ("RAMCOSYS", 20220630),
    ("MMTC", 20220630),
    ("TITAGARH", 20221231),
    ("RBLBANK", 20211231),
    ("BLISSGVS", 20211231),
    ("CCAVENUE", 20211231),
]


def d(x):
    x = int(x)
    return datetime.date(x // 10000, (x // 100) % 100, min(x % 100, 28))


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


def cv(s, q):
    for r in data.get(s, []):
        if r[0] == q:
            return r[3]
    return None


def pscore(t):
    low = t.lower()
    s = 0
    if re.search(r"revenue from operations|interest earned|total income", low):
        s += 4
    if re.search(r"tax expense|current tax|provision for tax", low) or ("tax" in low and "profit" in low):
        s += 3
    if re.search(r"profit\s*/?\s*\(?loss\)?\s*for the (period|year)", low):
        s += 4
    if "consolidated" in low:
        s += 4
    if "attributable" in low and "owner" in low:
        s += 4
    if re.search(r"earnings per|related party|board of directors approved|outcome of", low) and "income" not in low:
        s -= 6
    s += min(len(NUMTOK.findall(t)) / 30.0, 5)
    return s


def docscore(doc):
    return max((pscore(doc[p].get_text()) for p in range(min(len(doc), 26))), default=-99)


def best_con_page(doc):
    best = (-1, 0)
    for p in range(min(len(doc), 26)):
        sc = pscore(doc[p].get_text())
        if sc > best[0]:
            best = (sc, p)
    return best[1]


def fetch_pdf(o, att):
    for base in ("AttachHis", "AttachLive"):
        try:
            dd = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if dd[:4] == b"%PDF":
                return dd
        except Exception:
            pass
    return None


o = V.session()
for i, (sym, qe) in enumerate(TARGETS):
    if sym not in codes:
        print("=== %s %d NOCODE" % (sym, qe))
        continue
    saved = os.path.join(OUT, "%s_%d.pdf" % (sym, qe))
    if os.path.exists(saved):
        best = (0, open(saved, "rb").read(), 0)
    else:
        if i and i % 8 == 0:
            time.sleep(2)
            o = V.session()
        try:
            fl = V.filings(o, codes[sym], pages=20, since="%d0101" % (qe // 10000))
        except Exception:
            print("=== %s %d FILINGS-ERR" % (sym, qe))
            continue
        cands = [(a, att) for a, att in fl if a and 18 <= (d(a) - d(qe)).days <= 135]
        best = None
        for a, att in sorted(cands)[:4]:
            pdf = fetch_pdf(o, att)
            if not pdf:
                continue
            try:
                doc = fitz.open(stream=pdf, filetype="pdf")
            except Exception:
                continue
            if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
                continue
            sc = docscore(doc)
            if best is None or sc > best[0]:
                best = (sc, pdf, a)
        if not best:
            print("=== %s %d  no-good-results-pdf (cands=%d)" % (sym, qe, len(cands)))
            continue
        open(saved, "wb").write(best[1])
    doc = fitz.open(stream=best[1], filetype="pdf")
    bp = best_con_page(doc)
    pv, yv = cv(sym, prevq(qe)), cv(sym, qe - 10000)
    print("=== %s %d  score=%.1f p%d  prev=%s yago=%s ===" % (sym, qe, best[0], bp + 1, pv, yv))
    rows = defaultdict(list)
    for w in doc[bp].get_text("words"):
        rows[round(w[1] / 3) * 3].append((w[0], w[4]))
    for y in sorted(rows):
        cells = sorted(rows[y])
        lab = " ".join(w for _, w in cells if not NUM.match(w.replace(",", "")))
        nums = [w for _, w in cells if NUM.match(w.replace(",", ""))]
        l = lab.lower()
        if len(nums) >= 2 and ("profit" in l or "owner" in l or "attributable" in l) and "before" not in l:
            print("   %-40s | %s" % (lab[:40], " ".join(nums[:5])))
print("DONE")
