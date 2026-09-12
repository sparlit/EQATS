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
"""Generalize the proven M&M owners extraction to a list of candidate material-NCI stocks (absent
from _reattr_owners). For each: fetch ~quarterly BSE result filings across 2020-2026, extract the
consolidated 'attributable to owners of the parent' row (ann-based column mapping: col0=current,
col1=prev, col2=year-ago), cross-filing consensus. Writes _owners_multi.json {sym:{qe:owners}}.
Does NOT modify sf_fundamentals (review + apply separately). Resumable per (sym,ann) PDF cache.
Run: python -X utf8 build_owners_multi.py
"""
import json
import os
import re
import statistics
import time
from collections import defaultdict

import bse_vision as V
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
OUTF = os.path.join(HERE, "_owners_multi.json")
CAND = [
    "BBTC",
    "BAJAJHLDNG",
    "JSWHL",
    "CHOLAHLDNG",
    "GODREJIND",
    "MAXINDIA",
    "GODREJAGRO",
    "TATAINVEST",
    "GVKPIL",
    "SBIN",
    "BANKBARODA",
    "CANBK",
    "AXISBANK",
    "FEDERALBNK",
    "AMBUJACEM",
    "ADANIENT",
    "GRASIM",
    "JSWENERGY",
    "TATAPOWER",
    "GMRAIRPORT",
]
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
WINS = [
    ("20200715", "20201130"),
    ("20210115", "20210531"),
    ("20210715", "20211130"),
    ("20220115", "20220531"),
    ("20220715", "20221130"),
    ("20230115", "20230531"),
    ("20230715", "20231130"),
    ("20240115", "20240531"),
    ("20240715", "20241130"),
    ("20250115", "20250531"),
    ("20250715", "20251130"),
    ("20260115", "20260531"),
    ("20211001", "20211215"),
    ("20200601", "20200810"),
]


def qa(a):
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


def pq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


def tv(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


o = V.session()


def datebound(code, lo, hi):
    out = []
    for pg in range(1, 3):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C" % (pg, lo, code, hi)
        )
        try:
            rows = json.loads(V.get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            if V.is_result(r) and r.get("ATTACHMENTNAME"):
                a = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                out.append((int(a) if a else 0, r["ATTACHMENTNAME"]))
        if len(rows) < 50:
            break
    return out


def fetch(att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            pass
    return None


def owners_row(pdf):
    doc = fitz.open(stream=pdf, filetype="pdf")
    con = False
    for p in range(min(len(doc), 24)):
        low = doc[p].get_text().lower()
        if "consolidated" in low:
            con = True
        elif re.search(r"standalone\s+(statement|financial|results)", low) and "consolidated" not in low:
            con = False
        if not con:
            continue
        rows = defaultdict(list)
        for w in doc[p].get_text("words"):
            rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            cells = sorted(rows[y])
            lab = " ".join(w for _, w in cells if not NUM.match(w.replace(",", "")))
            l = lab.lower()
            if re.search(r"(owners|equity ?holders) of the (parent|company)", l) and "comprehensive" not in l:
                nums = [tv(w) for _, w in cells if NUM.match(w.replace(",", ""))]
                nums = [v for v in nums if v is not None]
                if len(nums) >= 2:
                    return nums
    return None


def main():
    out = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    for sym in CAND:
        if sym in out:
            continue
        code = scrips.get(sym) or {"GSPL": 532702}.get(sym)
        if not code:
            out[sym] = {"_note": "nocode"}
            continue
        cache = os.path.join(HERE, "_own", sym)
        os.makedirs(cache, exist_ok=True)
        anns = set()
        for lo, hi in WINS:
            fl = datebound(code, lo, hi)
            if fl:
                ann, att = min(fl)
                if ann not in anns:
                    fn = os.path.join(cache, "%d.pdf" % ann)
                    if not os.path.exists(fn):
                        pdf = fetch(att)
                        if pdf:
                            open(fn, "wb").write(pdf)
                    anns.add(ann)
            time.sleep(0.3)
        acc = defaultdict(list)
        for fn in os.listdir(cache):
            ann = int(fn[:-4])
            qe0 = qa(ann)
            try:
                nums = owners_row(open(os.path.join(cache, fn), "rb").read())
            except Exception:
                nums = None
            if not nums:
                continue
            for i, q in enumerate([qe0, pq(qe0), qe0 - 10000]):
                if i < len(nums):
                    acc[q].append(nums[i])
        ser = {}
        for q in sorted(acc):
            vals = acc[q]
            best = []
            for v in vals:
                g = [x for x in vals if abs(x - v) <= max(0.5, abs(v) * 0.02)]
                if len(g) > len(best):
                    best = g
            ser[str(q)] = round(statistics.median(best), 2)
        out[sym] = ser
        print("  %-12s %d owners-quarters extracted" % (sym, len(ser)), flush=True)
        json.dump(out, open(OUTF, "w"))
    json.dump(out, open(OUTF, "w"))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
