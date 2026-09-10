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
"""Exhaustive BSE gap recovery: for every remaining con-basis gap quarter, fetch the BSE filing
whose CURRENT-quarter column == the gap quarter, read the CONSOLIDATED net profit (owners-
attributable when an NCI split exists, else 'profit for the period') from the PDF text layer by
y-coordinate, convert units, and gate against the bracketing quarters in sf_fundamentals.json.

Output _bse_render_results.json: [[sym, qe, value_cr, ann, status, prevCon, nextCon], ...]
  status: FILL (passed neighbor gate) | MANUAL (extracted but implausible -> render & eyeball)
          | NOFILE (no BSE filing for that quarter) | DEFUNCT/NOCODE (skipped)
Resumable: per-symbol PDFs cached in _vpdf/. Run: python -X utf8 bse_render_extract.py
"""
import datetime
import json
import os
import re
import sys
import time
from collections import defaultdict

import bse_vision as V
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")
codes = json.load(open(os.path.join(HERE, "_gap_codes.json")))
codes.setdefault("GSPL", 532702)
codes.setdefault("PEL", 500302)
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
}  # delisted/defunct or dead-zone (both feeds gap)
data = json.load(open(DOCS))
VP = os.path.join(HERE, "_vpdf")
os.makedirs(VP, exist_ok=True)

NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
OWN = re.compile(r"(owners|equity holders) of the (parent|company|holding)", re.IGNORECASE)
PFT = re.compile(r"(net\s+)?profit\s*/?\s*\(?\s*loss\)?\s*(after tax\s*)?for the (period|year|quarter)", re.IGNORECASE)


def detect_div(doc):
    t = " ".join(doc[p].get_text() for p in range(min(len(doc), 8))).lower()
    if re.search(r"in\s+lakh|in\s+lac|lakhs", t):
        return 100.0
    if re.search(r"in\s+million|in\s+mn\b|millions", t):
        return 10.0
    if re.search(r"in\s+crore|crores|in\s+cr\b", t):
        return 1.0
    return None


def to_val(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


def row_nums(cells):
    return [to_val(w) for x, w in sorted(cells) if NUM.match(w.replace(",", "")) and to_val(w) is not None]


def extract(pdf):
    """Return (value_cr, div) — consolidated current-quarter (col0) owners profit, else profit-for-period."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        return None, None  # scanned, no text layer
    div = detect_div(doc) or 1.0
    con = False
    owners = pfp = None
    for p in range(min(len(doc), 26)):
        low = doc[p].get_text().lower()
        if re.search(r"consolidated\s+(statement|financial|results|segment|un|ind)", low):
            con = True
        elif re.search(r"standalone\s+(statement|financial|results|segment|un|ind)", low):
            con = False
        if not con:
            continue
        rows = defaultdict(list)
        for w in doc[p].get_text("words"):
            rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            txt = " ".join(w for _, w in sorted(rows[y]))
            l = txt.lower()
            if OWN.search(l) and owners is None:
                n = row_nums(rows[y])
                if n:
                    owners = n[0]
            elif PFT.search(l) and "before" not in l and "comprehensive" not in l and pfp is None:
                n = row_nums(rows[y])
                if n:
                    pfp = n[0]
    val = owners if owners is not None else pfp
    return (round(val / div, 2) if val is not None else None), div


def neighbors(arr, qe):
    p = n = None
    for r in arr:
        if r[3] is None:
            continue
        if r[0] < qe and (p is None or r[0] > p[0]):
            p = (r[0], r[3])
        if r[0] > qe and (n is None or r[0] < n[0]):
            n = (r[0], r[3])
    return (p[1] if p else None), (n[1] if n else None)


def plausible(v, cp, cn):
    ns = [abs(x) for x in (cp, cn) if x is not None]
    if v is None or not ns:
        return False
    lo, hi = min(ns), max(ns)
    if abs(v) < max(lo * 0.2, 0.5):
        return False
    if abs(v) > hi * 5 + 5:
        return False
    return True


def d(x):
    x = int(x)
    return datetime.date(x // 10000, (x // 100) % 100, min(x % 100, 28))


def fetch_for(sym, qe, o):
    fn = os.path.join(VP, "%s_%d.pdf" % (sym, qe))
    if os.path.exists(fn) and os.path.getsize(fn) > 4:
        return open(fn, "rb").read()
    try:
        fl = V.filings(o, codes[sym], pages=25, since="%d0101" % (qe // 10000 - 1))
    except Exception:
        return None
    cands = [(a, att) for a, att in fl if a and 12 <= (d(a) - d(qe)).days <= 150]
    if not cands:
        return None
    _a, att = min(cands)
    for base in ("AttachHis", "AttachLive"):
        try:
            dd = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if dd[:4] == b"%PDF":
                open(fn, "wb").write(dd)
                return dd
        except Exception:
            pass
    return None


def main():
    vq = json.load(open(os.path.join(HERE, "_bse_vision_queue.json")))
    nd = json.load(open(os.path.join(HERE, "_bse_nodata.json")))
    work = sorted({(s, q) for s, q in (vq + nd)})
    rf = os.path.join(HERE, "_bse_render_results.json")
    out = json.load(open(rf)) if os.path.exists(rf) else []
    done = {(s, q) for s, q, *_ in out}
    o = V.session()
    proc = 0
    for sym, qe in work:
        if (sym, qe) in done:
            continue
        cp, cn = neighbors(data.get(sym, []), qe)
        if sym in DEFUNCT:
            out.append([sym, qe, None, None, "DEFUNCT", cp, cn])
            continue
        if sym not in codes:
            out.append([sym, qe, None, None, "NOCODE", cp, cn])
            continue
        try:
            if proc and proc % 10 == 0:
                time.sleep(2)
                o = V.session()
            proc += 1
            pdf = fetch_for(sym, qe, o)
            if not pdf:
                out.append([sym, qe, None, None, "NOFILE", cp, cn])
                print("  %-11s %d NOFILE" % (sym, qe), flush=True)
            else:
                try:
                    val, _div = extract(pdf)
                except Exception:
                    val = None
                if val is None:
                    out.append([sym, qe, None, None, "NOPARSE", cp, cn])
                    print("  %-11s %d NOPARSE" % (sym, qe), flush=True)
                else:
                    st = "FILL" if plausible(val, cp, cn) else "MANUAL"
                    out.append([sym, qe, val, None, st, cp, cn])
                    print("  %-11s %d  %s  val=%s  nbrs %s/%s" % (sym, qe, st, val, cp, cn), flush=True)
        except Exception as e:
            out.append([sym, qe, None, None, "ERR", cp, cn])
            print("  %-11s %d ERR %s" % (sym, qe, str(e)[:40]), flush=True)
        json.dump(out, open(os.path.join(HERE, "_bse_render_results.json"), "w"))
    json.dump(out, open(os.path.join(HERE, "_bse_render_results.json"), "w"))
    from collections import Counter

    print("STATUS:", dict(Counter(r[4] for r in out)), flush=True)


if __name__ == "__main__":
    main()
