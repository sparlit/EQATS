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
"""Final anchor pass: for each REMAINING con-basis gap with a text PDF, scan ALL pages, collect
consolidated owners/profit rows, and accept col0 (current/gap quarter) when a sibling column
anchors on a known stored neighbor (immediate-prev within 3% or year-ago) under some unit scale
(/1,/10,/100). Prefers an 'attributable to owners' row. Outputs _anchor_all.json.
Run: python -X utf8 bse_anchor_all.py
"""
import glob
import json
import os
import re
from collections import defaultdict

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
OWN = re.compile(r"(owners|equity ?holders|equityholders) of the (parent|company|holding|group)", re.IGNORECASE)
PFT = re.compile(
    r"(net\s+)?profit\s*/?\s*\(?\s*loss\)?\s*(after tax\s*)?(for|of)\s*the\s*(period|year|quarter)", re.IGNORECASE
)
DEFUNCT = {
    "DHFL",
    "HDFC",
    "ROLTA",
    "JPINFRATEC",
    "TATAMTRDVR",
    "CONSOFINVT",
    "UJJIVAN",
    "EROSMEDIA",
    "UNITECH",
    "GVPIL",
    "CYIENT",
    "IDEA",
}
Q = {3: 0, 6: 1, 9: 2, 12: 3}
INV = {v: k for k, v in Q.items()}


def qi(qe):
    m = (qe // 100) % 100
    return None if m not in Q else (qe // 10000) * 4 + Q[m]


def qefrom(idx):
    y, q = idx // 4, idx % 4
    mo = INV[q]
    return y * 10000 + mo * 100 + (31 if mo in (3, 12) else 30)


def conval(s, qe):
    for r in data.get(s, []):
        if r[0] == qe:
            return r[3]
    return None


def gaps():
    idx = json.load(open(os.path.join(HERE, "indices_history.json")))["Nifty 500"]
    M = set()
    for x in idx:
        M.update(x["symbols"])
    out = []
    for s in sorted(M):
        a = data.get(s)
        if not a or not any(r[3] is not None for r in a):
            continue
        cv = {r[0]: r[3] for r in a}
        sq = sorted({r[0] for r in a if (r[0] // 100) % 100 in Q and r[0] >= 20200101})
        for i in range(len(sq) - 1):
            x, y = sq[i], sq[i + 1]
            ia, ib = qi(x), qi(y)
            if ib - ia - 1 < 1 or ib - ia - 1 >= 3:
                continue
            ca, cb = cv.get(x), cv.get(y)
            if ca is not None and cb is not None and (abs(ca) >= 15 or abs(cb) >= 15):
                for k in range(ia + 1, ib):
                    out.append((s, qefrom(k)))
    return out


def to_val(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


def candidate_rows(doc):
    con = False
    out = []
    for p in range(min(len(doc), 28)):
        low = doc[p].get_text().lower()
        if "consolidated" in low:
            con = True
        elif re.search(r"standalone\s+(statement|financial|results|ind)", low) and "consolidated" not in low:
            con = False
        if not con:
            continue
        rows = defaultdict(list)
        for w in doc[p].get_text("words"):
            rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            cells = sorted(rows[y])
            txt = " ".join(w for _, w in cells)
            l = txt.lower()
            if "before" in l or "comprehensive" in l or "segment" in l:
                continue
            nums = [to_val(w) for _, w in cells if NUM.match(w.replace(",", ""))]
            nums = [v for v in nums if v is not None]
            if len(nums) >= 2 and (OWN.search(l) or PFT.search(l)):
                out.append(("OWN" if OWN.search(l) else "PFT", nums))
    return out


def anchor(nums, cprev, cyago):
    for div in (1.0, 100.0, 10.0):
        cols = [round(v / div, 2) for v in nums]
        for tgt, idx, nm in [(cprev, 1, "prev"), (cyago, 2, "yago")]:
            if tgt is None or idx >= len(cols) or abs(tgt) < 3:
                continue
            if abs(cols[idx] - tgt) <= abs(tgt) * 0.03:
                return cols[0], f"{nm}~{tgt}/{div:g}"
    return None


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


out = []
for s, qe in gaps():
    if s in DEFUNCT:
        continue
    fn = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (s, qe))
    if not os.path.exists(fn):
        continue
    try:
        doc = fitz.open(fn)
    except Exception:
        continue
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        continue
    cprev = conval(s, prevq(qe))
    cyago = conval(s, qe - 10000)
    best = None
    for tag, nums in candidate_rows(doc):
        m = anchor(nums, cprev, cyago)
        if m:
            best = (m[0], tag, m[1])
            if tag == "OWN":
                break
    if best:
        out.append([s, qe, best[0], f"{best[1]} {best[2]}"])
        print("  %-12s %d = %-10s [%s]" % (s, qe, best[0], best[2]))
json.dump(out, open(os.path.join(HERE, "_anchor_all.json"), "w"))
print("ANCHORED %d of remaining gaps" % len(out))
