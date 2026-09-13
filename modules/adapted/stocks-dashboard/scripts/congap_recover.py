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
"""Recover MISSING consolidated quarters across the Nifty 500 universe from BSE result filings.
SAFE / never-assume design: for each (sym, gap-quarter) in _congap_targets.json, fetch the BSE filing
that REPORTS that quarter, text-parse the consolidated P&L, and accept col0 (the gap quarter) ONLY when
BOTH sibling columns anchor on STORED neighbors -- col1 == preceding-quarter con AND col2 == year-ago
con, each within 3%, under one consistent unit scale (/1,/10,/100). Two independent confirmations make a
mis-grouped/garbled row essentially impossible to accept (single-anchor was shown to mis-read e.g. ALKEM
179.7 vs the true 127.64). Prefers the 'attributable to owners' row (owners-basis). Resumable (caches
PDFs in _vpdf/, saves _congap_recovered.json incrementally). Does NOT modify sf_fundamentals.
Run: python -X utf8 congap_recover.py
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_vision as V
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "..", "docs", "sf_fundamentals.json")))
scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
targets = json.load(open(os.path.join(HERE, "_congap_targets.json")))
OUTF = os.path.join(HERE, "_congap_recovered.json")
VPDF = os.path.join(HERE, "_vpdf")
os.makedirs(VPDF, exist_ok=True)
DEFUNCT = {"DHFL", "HDFC", "ROLTA", "JPINFRATEC", "TATAMTRDVR", "CONSOFINVT", "EROSMEDIA", "UNITECH", "GVKPIL"}

NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
OWN = re.compile(r"(owners|equity ?holders|equityholders|attributab)", re.IGNORECASE)


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}[md]


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


def window(q):
    y, md = q // 10000, q % 10000
    hi = {331: y * 10000 + 831, 630: y * 10000 + 1130, 930: (y + 1) * 10000 + 301, 1231: (y + 1) * 10000 + 601}[md]
    return str(q), str(hi)


def conval(s, qe):
    for r in data.get(s, []):
        if r[0] == qe:
            return r[3]
    return None


def tv(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


def datebound(o, code, lo, hi):
    out = []
    for pg in range(1, 4):
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
    return sorted(set(out))


def fetch(o, att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            pass
    return None


def rows_con(pdf):
    """Consolidated profit/owners rows. Tolerance line-grouping (handles split rows) + loose label
    (catches OCR-truncated 'profit for the perio...'). Returns [(tag, [nums left-to-right]), ...]."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return []
    con = False
    out = []
    for p in range(min(len(doc), 28)):
        low = doc[p].get_text().lower()
        if "consolidated" in low:
            con = True
        elif (
            re.search(r"standalone\s+(statement|financial|results|unaudited|audited|ind)", low)
            and "consolidated" not in low
        ):
            con = False
        if not con:
            continue
        ws = sorted(doc[p].get_text("words"), key=lambda w: (round(w[1]), w[0]))
        lines = []
        cur = []
        cy = None
        for w in ws:
            if cy is None or abs(w[1] - cy) <= 4:
                cur.append(w)
            else:
                lines.append(cur)
                cur = [w]
            cy = w[1]
        if cur:
            lines.append(cur)
        for ln in lines:
            cells = sorted(ln, key=lambda w: w[0])
            l = " ".join(w[4] for w in cells).lower()
            if any(x in l for x in ("before", "comprehensive", "segment", "exceptional")):
                continue
            nums = [tv(w[4]) for w in cells if NUM.match(w[4].replace(",", ""))]
            nums = [v for v in nums if v is not None]
            if len(nums) < 3:
                continue
            isown = bool(OWN.search(l))
            ispft = (
                "profit for the" in l
                or "profit/(loss) for" in l
                or "profit /(loss) for" in l
                or bool(re.search(r"profit\s*/?\s*\(?loss\)?\s*(after tax|for the|of the)", l))
            )
            if isown or ispft:
                out.append(("OWN" if isown else "PFT", nums))
    return out


def double_anchor(nums, cprev, cyago):
    """Accept col0 ONLY if col1==prev-quarter AND col2==year-ago, both within 3%, same unit scale."""
    if cprev is None or cyago is None or abs(cprev) < 3 or abs(cyago) < 3:
        return None
    for div in (1.0, 100.0, 10.0):
        c = [round(v / div, 2) for v in nums]
        if len(c) > 2 and abs(c[1] - cprev) <= abs(cprev) * 0.03 and abs(c[2] - cyago) <= abs(cyago) * 0.03:
            return c[0], f"BOTH prev~{cprev:.1f} yago~{cyago:.1f} /{div:g}"
    return None


def anchor_pdf(pdf, cprev, cyago):
    rc = rows_con(pdf)
    if not rc:
        return None, "no-con-text"
    best = None
    for tag, nums in rc:
        a = double_anchor(nums, cprev, cyago)
        if a:
            if tag == "OWN":
                return a  # owners row + double anchor = best
            if best is None:
                best = a
    return best or (None, "no-double-anchor")


def main():
    recovered = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    work = [(s, q) for s, gs in targets.items() for q in gs]
    o = V.session()
    done = ok = 0
    HB = os.path.join(HERE, "_congap_hb.txt")

    def save():
        json.dump(recovered, open(OUTF + ".tmp", "w"))
        os.replace(OUTF + ".tmp", OUTF)  # atomic: kill-safe
        open(HB, "w").write(str(time.time()))  # heartbeat for the monitor

    save()
    for n, (sym, q) in enumerate(work):
        key = "%s|%d" % (sym, q)
        if key in recovered:
            if recovered[key].get("v") is not None:
                ok += 1
            continue
        code = scrips.get(sym)
        if not code or sym in DEFUNCT:
            recovered[key] = {"v": None, "why": "nocode/defunct"}
            continue
        cprev = conval(sym, prevq(q))
        cyago = conval(sym, q - 10000)
        pdfpath = os.path.join(VPDF, "%s_%d.pdf" % (sym, q))
        val = None
        info = "nopdf"
        if os.path.exists(pdfpath):
            try:
                val, info = anchor_pdf(open(pdfpath, "rb").read(), cprev, cyago)
            except Exception:
                val, info = None, "parse-err"
        if val is None and (cprev is not None or cyago is not None):
            lo, hi = window(q)
            try:
                fl = [(a, att) for a, att in datebound(o, code, lo, hi) if qe_from_ann(a) == q]
            except Exception:
                fl = []
            for _a, att in fl[:3]:
                try:
                    pdf = fetch(o, att)
                except Exception:
                    pdf = None
                time.sleep(2)
                if not pdf:
                    continue
                if not os.path.exists(pdfpath):
                    open(pdfpath, "wb").write(pdf)
                v2, i2 = anchor_pdf(pdf, cprev, cyago)
                if v2 is not None:
                    val, info = v2, i2
                    break
                info = i2
        recovered[key] = {"v": val, "why": info}
        done += 1
        if val is not None:
            ok += 1
        if done % 10 == 0:
            save()
            print(
                "  ...%d/%d processed, %d double-anchored (last %s|%d=%s)" % (n + 1, len(work), ok, sym, q, val),
                flush=True,
            )
    save()
    print("DONE. double-anchored %d of %d target gap-quarters." % (ok, len(work)), flush=True)


if __name__ == "__main__":
    main()
