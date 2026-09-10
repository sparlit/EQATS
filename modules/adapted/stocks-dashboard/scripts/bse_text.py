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
"""Fast, exact BSE results backfill from the PDF TEXT LAYER (no OCR, no vision). For each results
filing, reconstruct table rows by y-coordinate, find the net-profit-after-tax row in the standalone
and consolidated sections (sticky heading context), and take the CURRENT-quarter value (first data
column, to the right of the label). Quarter-end inferred from the filing month, refined by any
'quarter ended <date>' in the text. Falls back to None (caller can vision-read) if no text layer.

  python bse_text.py MCX 534091 --since 20140101
Writes scripts/_bse_text/<SYM>.json = [[qe, std, con, ann], ...]
"""
import json
import os
import re
import sys
import time

import bse_vision as V
import fitz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bse_text")
os.makedirs(OUT, exist_ok=True)
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
NETPAT = re.compile(
    r"(net\s*profit\s*(/\s*\(loss\)\s*)?\s*(after\s*tax|for\s*the)|"
    r"(\(loss\)\s*/?\s*)?profit\s*(/\s*\(loss\)\s*)?\s*for\s*the\s*(period|quarter|year))",
    re.IGNORECASE,
)
EXCL = re.compile(
    r"before\s*tax|comprehensive|margin|debt|earning|share\s*of|associate(?!s)|operating|segment", re.IGNORECASE
)
MON = {
    "january": "03",
    "february": "03",
    "march": "03",
    "april": "06",
    "may": "06",
    "june": "06",
    "july": "09",
    "august": "09",
    "september": "09",
    "october": "12",
    "november": "12",
    "december": "12",
}
# quarter-end for "... ended <Mon> <day>, <year>"
QEND = re.compile(r"ended\s+(\d{1,2})?\s*([a-z]+)[,\s]+(\d{4})", re.IGNORECASE)


def to_val(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


def qe_from_ann(ann):
    y, m = ann // 10000, (ann // 100) % 100
    if 7 <= m <= 9:
        return y * 10000 + 630
    if 10 <= m <= 12:
        return y * 10000 + 930
    if 1 <= m <= 3:
        return (y - 1) * 10000 + 1231
    if 4 <= m <= 6:
        return y * 10000 + 331
    return 0


def rows_by_y(pg):
    out = {}
    for x0, y0, x1, y1, w, _b, _l, _n in pg.get_text("words"):
        out.setdefault(round((y0 + y1) / 2 / 3.0), []).append(((x0 + x1) / 2, w))
    for k in out:
        out[k].sort()
    return out


def data_after_label(cells):
    """numeric tokens to the right of the last alphabetic label token (drops the leading row #)."""
    lab_x = -1
    for xc, w in cells:
        if re.search(r"[a-zA-Z]", w):
            lab_x = max(lab_x, xc)
    nums = [to_val(w) for xc, w in cells if xc > lab_x and NUM.match(w.replace(",", ""))]
    return [v for v in nums if v is not None]


UNIT_DECL = re.compile(
    r"(?:figures?|amounts?|values?|rs\.?|₹|inr)[^.\n]{0,25}?in\s+(crores?|lakhs?|lacs?|millions?)", re.IGNORECASE
)
UNIT_PAREN = re.compile(r"\(\s*(?:₹|rs\.?|inr)?\s*in\s+(crores?|lakhs?|lacs?|millions?)\s*\)", re.IGNORECASE)


def detect_unit(low):
    # trust explicit statement declarations first; crore wins (stray "lakh/million" notes shouldn't override)
    norm = set()
    for d in UNIT_DECL.findall(low) + UNIT_PAREN.findall(low):
        d = d.lower()
        norm.add("cr" if d.startswith("crore") else "lk" if d[:3] in ("lak", "lac") else "mn")
    if "cr" in norm:
        return 1.0
    if "lk" in norm:
        return 100.0
    if "mn" in norm:
        return 10.0
    if re.search(r"in\s*lakh|in\s*lac|lakhs", low):
        return 100.0  # loose fallback
    if re.search(r"in\s*million|millions", low):
        return 10.0
    if re.search(r"in\s*crore|crores", low):
        return 1.0
    return None


def parse_pdf(pdf, ann):
    doc = fitz.open(stream=pdf, filetype="pdf")
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        return None  # scanned, no text layer
    full = " ".join(doc[p].get_text() for p in range(min(len(doc), 10))).lower()
    div = detect_unit(full) or 1.0
    con_ctx = False
    qe_txt = None
    cands = []  # (rownum_or_None, con_ctx_at_row, nums, combined_bool)
    for pi in range(min(len(doc), 24)):
        pg = doc[pi]
        low = pg.get_text().lower()
        if qe_txt is None:
            m = QEND.search(low)
            if m and m.group(2).lower() in MON:
                qe_txt = int(m.group(3) + MON[m.group(2).lower()] + "31")
        if re.search(r"consolidated\s+(statement|financial|results|segment|un)", low):
            con_ctx = True
        elif re.search(r"standalone\s+(statement|financial|results|segment|un)", low):
            con_ctx = False
        for cells in rows_by_y(pg).values():
            txt = " ".join(w for _, w in cells)
            if NETPAT.search(txt) and not EXCL.search(txt):
                nums = data_after_label(cells)
                if len(nums) < 3:
                    continue
                m = re.search(r"\(\s*(\d+)\s*[-–]\s*\d+\s*\)", txt)  # "(5-6)" -> 5
                rn = int(m.group(1)) if m else None
                cands.append((rn, con_ctx, nums))
    std_v = con_v = None
    combined = [c for c in cands if len(c[2]) >= 10]
    if combined:  # std+con on one row: con cols 1..6, std cols 7..12
        n = combined[0][2]
        half = len(n) // 2
        con_v, std_v = n[0:3], n[half : half + 3]
    else:
        rned = [c for c in cands if c[0] is not None]
        if len({c[0] for c in rned}) >= 2:  # distinct row-numbers: lowest=std, highest=con
            lo = min(c[0] for c in rned)
            hi = max(c[0] for c in rned)
            std_v = next(c[2] for c in rned if c[0] == lo)[0:3]
            con_v = next(c[2] for c in rned if c[0] == hi)[0:3]
        else:  # fall back to heading context
            for rn, cc, nums in cands:
                if cc and con_v is None:
                    con_v = nums[0:3]
                elif not cc and std_v is None:
                    std_v = nums[0:3]
    sc = [round(v / div, 2) for v in std_v] if std_v else None
    cc = [round(v / div, 2) for v in con_v] if con_v else None
    return sc, cc, qe_txt


def prev_q(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}.get(md, 0)


def consensus(vals):
    """largest cluster (within 3% tol) -> (median, support, total). None if empty."""
    import statistics

    if not vals:
        return None, 0, 0
    best = []
    for v in vals:
        tol = max(0.5, abs(v) * 0.03)
        g = [x for x in vals if abs(x - v) <= tol]
        if len(g) > len(best):
            best = g
    return round(statistics.median(best), 2), len(best), len(vals)


def main():
    a = sys.argv[1:]
    since = "20080101"
    if "--since" in a:
        i = a.index("--since")
        since = a[i + 1]
        a = a[:i] + a[i + 2 :]
    sym, code = a[0], int(a[1])
    o = V.session()
    fl = V.filings(o, code, pages=30, since=since)
    print(
        "%s: %d result filings %s..%s" % (sym, len(fl), min(x[0] for x in fl if x[0]), max(x[0] for x in fl)),
        flush=True,
    )
    obs = {}
    anns = {}  # obs[(qe,basis)] = [values];  anns[qe] = earliest ann
    for ann, att in sorted(fl):
        pdf = None
        for base in ("AttachHis", "AttachLive"):
            try:
                d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
                if d[:4] == b"%PDF":
                    pdf = d
                    break
            except Exception:
                continue
        if not pdf:
            continue
        try:
            r = parse_pdf(pdf, ann)
        except Exception:
            r = None
        if not r:
            print("  ann=%d  NO-TEXT/parse-fail" % ann, flush=True)
            continue
        std_c, con_c, _ = r
        qe = qe_from_ann(ann)
        anns[qe] = min(ann, anns.get(qe, ann))
        for basis, cols in (("s", std_c), ("c", con_c)):
            if not cols:
                continue
            qmap = [qe, prev_q(qe), qe - 10000]  # col0=current, col1=preceding, col2=year-ago
            for ci, val in enumerate(cols[:3]):
                tq = qmap[ci]
                if tq:
                    obs.setdefault((tq, basis), []).append(val)
        print("  ann=%d qe=%d std=%s con=%s" % (ann, qe, std_c, con_c), flush=True)
        time.sleep(0.4)
    qes = sorted({q for q, b in obs})
    arr = []
    for qe in qes:
        sv, ss, st = consensus(obs.get((qe, "s"), []))
        cv, cs, ct = consensus(obs.get((qe, "c"), []))
        arr.append([qe, sv, cv, anns.get(qe, 0), [ss, st], [cs, ct]])
    # magnitude correction: a value ~100x the series median is an undivided-lakh artifact
    import statistics

    for idx in (1, 2):
        vals = [abs(r[idx]) for r in arr if r[idx] is not None and abs(r[idx]) > 0.01]
        if len(vals) < 4:
            continue
        med = statistics.median(vals)
        for r in arr:
            if r[idx] is not None and med > 0 and abs(r[idx]) > med * 20:
                r[idx] = round(r[idx] / 100.0, 2)
    json.dump(arr, open(os.path.join(OUT, f"{sym}.json"), "w"))
    print(
        "DONE %s: %d quarters -> %s.json  (entries carry [std_support,total] [con_support,total])"
        % (sym, len(arr), sym),
        flush=True,
    )


if __name__ == "__main__":
    main()
