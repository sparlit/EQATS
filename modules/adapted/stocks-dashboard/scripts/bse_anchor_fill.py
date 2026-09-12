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
"""Anchor-validated extraction: for each cached gap PDF, read the consolidated profit row's
columns (col0=current/gap quarter, col1=preceding, col2=year-ago). ACCEPT col0 only if a sibling
column (col1 or col2) matches a KNOWN stored value (conPrev within 3%, or the year-ago quarter) —
this self-validates both the row choice AND the unit (we try /1,/10,/100 and keep the scaling that
makes a sibling match). Everything that can't be anchored is flagged MANUAL for an image read.

Output _bse_anchor.json: [[sym,qe,value_cr,anchor_desc,status],...]  status FILL|MANUAL|SCANNED
Run: python -X utf8 bse_anchor_fill.py
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
OWN = re.compile(r"(owners|equity holders) of the (parent|company|holding|group)", re.IGNORECASE)
PFT = re.compile(r"profit\s*/?\s*\(?\s*loss\)?\s*(after tax\s*)?(for|of)\s*the\s*(period|year|quarter)", re.IGNORECASE)


def to_val(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


def conval(arr, qe):
    for r in arr:
        if r[0] == qe:
            return r[3]
    return None


def neighbors(arr, qe):
    p = n = None
    for r in arr:
        if r[3] is None:
            continue
        if r[0] < qe and (p is None or r[0] > p[0]):
            p = (r[0], r[3])
        if r[0] > qe and (n is None or r[0] < n[0]):
            n = (r[0], r[3])
    return p, n


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


def rows_with_nums(doc):
    """yield (label_lower, [floats]) for consolidated owners/profit rows."""
    con = False
    for p in range(min(len(doc), 26)):
        low = doc[p].get_text().lower()
        if re.search(r"consolidated\s+(statement|financial|results|segment|un|ind|audited)", low):
            con = True
        elif re.search(r"standalone\s+(statement|financial|results|segment|un|ind|audited)", low):
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
            if "before" in l or "comprehensive" in l or "segment" in l or "equity attributable" in l:
                continue
            if OWN.search(l) or PFT.search(l):
                nums = [to_val(w) for _, w in cells if NUM.match(w.replace(",", ""))]
                nums = [v for v in nums if v is not None]
                if len(nums) >= 2:
                    yield ("OWN" if OWN.search(l) else "PFT"), nums


def anchor_match(nums, cprev, cyago):
    """Try div in {1,10,100}; if col1~cprev or col2~cyago, return (col0/div, desc). Else None."""
    for div in (1.0, 100.0, 10.0):
        cols = [round(v / div, 2) for v in nums]
        for tgt, idx, name in [(cprev, 1, "col1=conPrev"), (cyago, 2, "col2=yrago")]:
            if tgt is None or idx >= len(cols):
                continue
            ok = abs(cols[idx] - tgt) < 1 if abs(tgt) < 1 else abs(cols[idx] - tgt) <= max(1.0, abs(tgt) * 0.04)
            if ok:
                return cols[0], f"{name}({cols[idx]}~{tgt},/{div:g})"
    return None


def main():
    out = []
    for fn in sorted(glob.glob(os.path.join(HERE, "_vpdf", "*.pdf"))):
        base = os.path.basename(fn)[:-4]
        sym, qe = base.rsplit("_", 1)
        qe = int(qe)
        arr = data.get(sym, [])
        try:
            doc = fitz.open(fn)
        except Exception:
            out.append([sym, qe, None, "open-fail", "MANUAL"])
            continue
        if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
            out.append([sym, qe, None, "scanned", "SCANNED"])
            continue
        p_, n_ = neighbors(arr, qe)
        cprev = conval(arr, prevq(qe))
        if cprev is None and p_ and p_[0] == prevq(qe):
            cprev = p_[1]
        cyago = conval(arr, qe - 10000)
        best = None
        for tag, nums in rows_with_nums(doc):
            m = anchor_match(nums, cprev, cyago)
            if m:
                # prefer OWN rows; take first confident match
                best = (m[0], f"{tag} {m[1]}")
                if tag == "OWN":
                    break
        if best:
            out.append([sym, qe, best[0], best[1], "FILL"])
        else:
            out.append([sym, qe, None, f"no-anchor (prev={cprev})", "MANUAL"])
    json.dump(out, open(os.path.join(HERE, "_bse_anchor.json"), "w"))
    from collections import Counter

    fills = [r for r in out if r[4] == "FILL"]
    print("ANCHOR RESULTS:", dict(Counter(r[4] for r in out)))
    print("\n-- FILL (anchor-validated) --")
    for r in fills:
        print("  %-12s %d  val=%-10s  [%s]" % (r[0], r[1], r[2], r[3]))
    print("\n-- MANUAL (need image read) --")
    for r in out:
        if r[4] in ("MANUAL", "SCANNED"):
            print("  %-12s %d  %s" % (r[0], r[1], r[3]))


if __name__ == "__main__":
    main()
