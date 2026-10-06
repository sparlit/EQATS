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
"""Read an NSE SME half-yearly results PDF by GEOMETRY  (runbook §210a).

A statement page is found by its rows ("Revenue from operations" … "Profit … after tax / for the period"); its columns
are the period-end DATES printed in the header, each a word on the page with an x position. A figure belongs to the
column whose date sits above it (nearest x-centre); a row's figures are the numeric words on the label's line band.

read(path) -> [{"page", "basis": "s"|"c", "unit": crore multiplier|None, "unit_txt",
                "cols": [{"date": YYYYMMDD, "x": centre, "kind": "half"|"year"|None}],
                "rev": [v per col], "pat": [v per col], "text": bool}]
  values are as printed (unit applied by the caller only after the arithmetic check); "-" = 0; (x) = -x.
No decision is taken here: which column is H1 / H2 / FY is decided by the caller from the dates and the year's own
arithmetic (H1 + H2 = FY inside one March filing).
"""
import datetime
import re

MON = {
    m[:3]: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
NUM = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?$")
DASH = {"-", "–", "—", "--", "nil", "Nil", "NIL"}
REV_LAB = [
    r"r[eo]v[eo]nue\s+from\s+op[ae]rations?",
    r"income\s+from\s+operations?",
    r"net\s+sales",
    r"sales\s*/\s*income\s+from\s+operations",
    r"revenue\s+from\s+operation",
]
PAT_LAB = [
    r"profit\s*/?\s*\(?loss\)?\s*(for|after)",
    r"net\s+profit\s*/?\s*\(?loss\)?\s*(for|after)",
    r"profit\s+after\s+tax",
    r"profit\s+for\s+the\s+(period|year|half)",
    r"\(loss\)\s*/\s*profit\s+(for|after)",
    r"profit\s*\(\s*loss\s*\)\s*(for|after)",
    r"net\s+profit\s+after\s+tax",
    r"profit\s*/\s*\(loss\)\s+for\s+the",
]
UNIT = [
    (r"in\s+(rs\.?|inr|₹|rupees)?\s*\.?\s*(lakhs?|lacs?)", 1e-2, "lakh"),
    (r"(lakhs?|lacs?)\s*\)", 1e-2, "lakh"),
    (r"in\s+(rs\.?|inr|₹)?\s*crores?", 1.0, "crore"),
    (r"in\s+(rs\.?|inr|₹)?\s*thousands?", 1e-4, "thousand"),
    (r"in\s+(rs\.?|inr|₹)?\s*hundreds?", 1e-5, "hundred"),
    (r"in\s+(rs\.?|inr|₹)?\s*millions?", 1e-1, "million"),
    (
        r"amount\s+in\s+(rs\.?|inr|₹|rupees)\b(?!\s*\.?\s*(lakh|lac|crore|thousand|hundred|million))",
        1e-7,
        "rupee",
    ),
    (r"in\s+(rs\.?|inr|₹|rupees)\s*\)", 1e-7, "rupee"),
]


def num(t):
    t = t.strip().replace(" ", "").strip("|[]{}_‘’'\"`~:;")
    if t in DASH:
        return 0.0
    if not NUM.match(t) or t.startswith("(") != t.endswith(
        ")"
    ):  # "(9" / "12)" are a formula, not a figure
        return None
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    v = float(t.strip("()").replace(",", "").lstrip("-"))
    return -v if neg else v


def parse_date(s):
    s = re.sub(r"[,_|]", " ", s).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    for fmt in (
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d.%m.%y",
        "%d-%m-%y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d %b %Y",
        "%d-%B-%Y",
        "%d %B %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            if 2015 <= d.year <= 2030 and (d.month, d.day) in ((3, 31), (9, 30), (6, 30), (12, 31)):
                return d
        except ValueError:
            pass
    return None


def header_dates(words):
    """date anchors: single-word dates, and 2-4 word dates ('31st March 2023', '30 Sep 2022', 'March 31, 2023')"""
    out = []
    n = len(words)
    for i, w in enumerate(words):
        d = parse_date(w[4])
        if d:
            out.append((d, (w[0] + w[2]) / 2, w[1], w[3]))
            continue
        for k in (2, 3):
            if i + k < n + 1:
                ws = words[i : i + k]
                if (
                    max(x[1] for x in ws) - min(x[1] for x in ws) > 12
                ):  # must share a line (or wrap tightly)
                    continue
                s = " ".join(x[4] for x in ws)
                s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s)
                d = parse_date(s)
                if d:
                    out.append(
                        (
                            d,
                            (ws[0][0] + ws[-1][2]) / 2,
                            min(x[1] for x in ws),
                            max(x[3] for x in ws),
                        )
                    )
                    break
    return out


def find_label(lines, pats):
    for li, (_y0, _y1, txt, _ws) in enumerate(lines):
        low = txt.lower()
        for p in pats:
            if re.search(p, low):
                return li
    return None


def pat_line(lines, ri):
    """the FINAL profit line: among lines below revenue that name profit after tax / for the period AND carry figures,
    prefer 'for the period/year/half', else the last such line before EPS / paid-up capital"""
    if ri is None:
        return None
    cands = []
    for li in range(ri + 1, len(lines)):
        low = lines[li][2].lower()
        if re.search(
            r"earnings?\s+per\s+share|earning\s+per|paid[\s-]*up|face\s+value|reserves?\s+excluding",
            low,
        ):
            break
        if re.match(
            r"^\W*for\s+the\s+(period|perid|year|half)", low
        ):  # a label wrapped under "Profit/(Loss)"
            prev = " ".join(
                re.sub(r"[\d.,()|\[\]\-]+", " ", lines[x][2])
                for x in range(max(ri + 1, li - 2), li)
            ).lower()
            if re.search(r"profit", prev):
                low = prev + " profit " + low
        if any(re.search(p, low) for p in PAT_LAB) and not re.search(
            r"before\s+tax|discontinu|exceptional|share\s+of|minority|non[- ]controlling|comprehensive",
            low,
        ):
            nums = sum(1 for w in lines[li][3] if num(w[4]) is not None)
            wrapped = (
                li + 1 < len(lines)
                and sum(1 for w in lines[li + 1][3] if num(w[4]) is not None) >= 2
            )
            above = (
                li - 1 > ri
                and lines[li][1] - lines[li - 1][0] <= 16
                and sum(1 for w in lines[li - 1][3] if num(w[4]) is not None) >= 2
            )
            if nums >= 2 or wrapped or above:
                cands.append((bool(re.search(r"for\s+the\s+(period|year|half)", low)), li))
    if not cands:
        return None
    fin = [li for f, li in cands if f]
    return fin[-1] if fin else cands[-1][1]


def group_lines(words):
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - yc) <= 3.0:
            lines[-1][1].append(w)
        else:
            lines.append([yc, [w]])
    out = []
    for yc, L in lines:
        L.sort(key=lambda w: w[0])
        out.append((min(w[1] for w in L), max(w[3] for w in L), " ".join(w[4] for w in L), L))
    return out


def label_right(L):
    """the label ends at its last token that is not a clean figure — a formula '(5 - 6)' belongs to the label"""
    xs = [w[2] for w in L if num(w[4]) is None]
    return max(xs) if xs else min(w[0] for w in L)


ROW_DEC = [0]


def row_values(lines, li, cols, label_right):
    """figures of a row: numeric words under the header's date columns on the label's line (right of the label), then
    the next two lines (a wrapped label) and the line just ABOVE it (scans often print figures a few points above the
    label, or split a row's figures across both — AARON Sep-2020). Each figure goes to the nearest column; a slot is
    filled once. The row counts when all but at most one column are filled."""
    lo = min(c["x"] for c in cols) - 55
    hi = max(c["x"] for c in cols) + 55
    vals = [None] * len(cols)
    dec = 0
    for k in (0, -1, 1, 2):
        if not (0 <= li + k < len(lines)):
            continue
        if k == -1 and lines[li][1] - lines[li - 1][0] > 16:
            continue
        if k > 0 and sum(1 for v in vals if v is not None) >= len(cols) - 1:
            break
        y0, y1, txt, L = lines[li + k]
        if (
            k > 0
            and re.search(r"[A-Za-z]{4,}", " ".join(w[4] for w in L if num(w[4]) is None))
            and sum(1 for v in vals if v is not None) > 0
        ):
            break  # the next labelled row has started
        for w in L:
            v = num(w[4])
            xc = (w[0] + w[2]) / 2
            if (
                v is None
                or not (lo <= xc <= hi)
                or (k >= 0 and w[0] < label_right - 2)
                or re.fullmatch(r"[IVX]+", w[4])
            ):
                continue
            j = min(range(len(cols)), key=lambda c: abs(cols[c]["x"] - xc))
            if vals[j] is None:
                vals[j] = v
                if "." in w[4]:
                    dec = max(dec, len(w[4].split(".")[1].rstrip(")|]}")))
    ROW_DEC[0] = dec
    return vals if sum(1 for v in vals if v is not None) >= max(2, len(cols) - 1) else None


def read(path):
    import fitz

    out = []
    doc = fitz.open(path)
    for pi, page in enumerate(doc):
        words = page.get_text("words")
        if not words:
            continue
        text = page.get_text().lower()
        if not re.search(
            r"r[eo]v[eo]nue|income\s+from\s+operation|net\s+sales", text
        ) or not re.search(r"profit", text):
            continue
        lines = group_lines(words)
        ri = find_label(lines, REV_LAB)
        pi_ = pat_line(lines, ri)
        if ri is None or pi_ is None:
            continue
        hd = [
            h
            for h in header_dates(sorted(words, key=lambda w: (w[1], w[0])))
            if h[2] < lines[ri][0]
        ]
        if len(hd) < 2:
            continue
        # the header line: the line (dates within 6 pt of each other) holding the most dates, nearest the revenue row —
        # never the title's date ("… for the year ended March 31, 2024" sits 30 pt higher, ACCENTMIC FY24)
        hd.sort(key=lambda h: h[2])
        groups = []
        for h in hd:
            if groups and h[2] - groups[-1][-1][2] <= 6:
                groups[-1].append(h)
            else:
                groups.append([h])
        best = max(groups, key=lambda g: (len(g), g[-1][2]))
        if len(best) < 2:
            continue
        band = max(h[2] for h in best)
        cols = sorted(best, key=lambda h: h[1])
        # de-duplicate anchors at the same x (a date split over two words read twice)
        C = []
        for d, x, _y0, _y1 in cols:
            if C and abs(C[-1]["x"] - x) < 8:
                continue
            C.append({"date": int(d.strftime("%Y%m%d")), "x": x})
        if len(C) < 2:
            continue
        # half / year label above each column: nearest "half"/"year"/"six months"/"twelve" word above the dates
        for c in C:
            above = [
                w
                for w in words
                if w[3] <= band + 2 and w[3] >= band - 60 and abs((w[0] + w[2]) / 2 - c["x"]) < 60
            ]
            t = " ".join(w[4].lower() for w in above)
            c["kind"] = (
                "half"
                if re.search(r"half|six\s*months|6\s*months", t)
                else ("year" if re.search(r"year|twelve|12\s*months", t) else None)
            )
        lr = label_right(lines[ri][3])
        pr = label_right(lines[pi_][3])
        rev = row_values(lines, ri, C, lr)
        dec = ROW_DEC[0]
        pat = row_values(lines, pi_, C, pr)
        dec = max(dec, ROW_DEC[0])
        # basic EPS (rupees per share — unit-free): the first "basic" line below the profit line
        eps = None
        for li in range(pi_ + 1, min(len(lines), pi_ + 14)):
            if re.search(r"\bbasic\b", lines[li][2].lower()):
                eps = row_values(lines, li, C, label_right(lines[li][3]))
                break
        top = page.get_text()[:2500].lower() + " " + " ".join(l[2].lower() for l in lines[:ri])
        unit = next(((m, lab) for p, m, lab in UNIT if re.search(p, top)), (None, None))
        basis = (
            "c"
            if re.search(r"consolidated\s+(statement|financial|results|audited|unaudited)", top)
            and not re.search(r"standalone", top)
            else "s"
        )
        area = page.rect.width * page.rect.height
        ocr = any(
            (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) > 0.5 * area
            for i in page.get_image_info()
        )
        out.append(
            {
                "page": pi,
                "basis": basis,
                "unit": unit[0],
                "unit_txt": unit[1],
                "cols": C,
                "rev": rev,
                "pat": pat,
                "eps": eps,
                "ocr": ocr,
                "dec": dec,
                "text": True,
            }
        )
    return out


if __name__ == "__main__":
    import json
    import sys

    for p in sys.argv[1:]:
        print(p)
        for r in read(p):
            print(json.dumps(r))


def _close(a, b, dec):
    """a == b to the filing's own rounding: 1.5 units of the last printed decimal (three rounded figures)"""
    return a is not None and b is not None and abs(a - b) <= 1.5 * 10 ** (-dec) + 1e-9


def decide(stmt, fy):
    """One statement page of a filing → {"H1": (rev, pat), "H2": …, "FY": …} for fiscal year ending 31-Mar-`fy` (as printed,
    unit NOT applied), with "how". H2 / FY are the two columns dated 31-Mar-fy (FY = the 'year' one, or whichever makes
    H1 + H2 = FY); H1 = the column dated 30-Sep-(fy-1). The year must CLOSE: revenue H1 + H2 = FY, and profit too when
    printed — a year whose revenue is 0 on every side proves nothing by itself (memory: 0+0=0) and then needs profit to
    close with non-zero figures."""
    C, R, P = stmt["cols"], stmt["rev"] or [], stmt["pat"] or []

    def at(i, arr):
        return arr[i] if i is not None and i < len(arr) else None

    h1 = [i for i, c in enumerate(C) if c["date"] == (fy - 1) * 10000 + 930]
    m = [i for i, c in enumerate(C) if c["date"] == fy * 10000 + 331]
    out = {}
    if h1:
        i1 = h1[0]
        out["H1"] = (at(i1, R), at(i1, P))
    if h1 and len(m) >= 2:
        yr = [i for i in m if C[i]["kind"] == "year"]
        orders = [(i2, iy) for i2 in m for iy in m if i2 != iy]
        if yr:
            orders = [(i2, iy) for i2, iy in orders if iy == yr[0]] + [
                o for o in orders if o[1] != yr[0]
            ]
        for i2, iy in orders:
            r1, r2, rf = at(h1[0], R), at(i2, R), at(iy, R)
            p1, p2, pf = at(h1[0], P), at(i2, P), at(iy, P)
            rev_ok = None not in (r1, r2, rf) and _close(r1 + r2, rf, stmt.get("dec", 0))
            pat_ok = None not in (p1, p2, pf) and _close(p1 + p2, pf, stmt.get("dec", 0))
            nonzero_rev = rf not in (None, 0.0)
            nonzero_pat = pf not in (None, 0.0) and p1 not in (None, 0.0) and p2 not in (None, 0.0)
            if stmt.get("ocr") and not (
                rev_ok and pat_ok
            ):  # an OCR'd page lands only when BOTH close (§168h)
                continue
            if (
                rev_ok
                and (pat_ok or None in (p1, p2, pf))
                and (nonzero_rev or (pat_ok and nonzero_pat))
            ):
                out["H2"] = (r2, p2)
                out["FY"] = (rf, pf)
                out["idx"] = {"H1": h1[0], "H2": i2, "FY": iy}
                out["how"] = "closes" + ("" if pat_ok else " (revenue only)")
                break
    return out
