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
"""§108 PASS 3 — the decisive test, against the ORIGINAL and the YEAR-LATER filing PDFs.

The restated-comparative class has one signature no feed can settle (§108): the stored value is the
figure the company FIRST PUBLISHED A YEAR LATER, as the comparative column of the next year's
filing, while the filing made on the stored ann date carried a different number. So ask both
documents:

    original  filing for qe        -> does it print the DETRES value?   (as-filed vintage)
    year-later filing for qe+1yr   -> does it print the STORED value?   (restated comparative)

Both true = the class, proven from the filer's own documents. Only the first true = the store is
simply wrong (a bad read), still a heal but a different `why`. Neither = re-adjudicate; do not heal.

DISCIPLINE
  * Filings are located by the POST-QUARTER STRETCH qe+8d..qe+150d, never the stored ann date —
    for pre-2018 quarters that date is frequently a qe+45d default and a tight window finds
    nothing (§52.1).
  * Attachments before ~Nov-2018 404 on both bases every fetcher tries; fetch_insurers.fetch_pdf
    falls back to BSE's own AnnPdfOpen.aspx resolver, which is what makes this era reachable
    (memory: reference-bse-attachment-resolver).
  * The number test is run at every plausible printed scale (crore / lakh / million / thousand)
    because the scale is a property of the document, not of our store.
  * ⚠️ THIS TOOL PROPOSES EVIDENCE, IT DOES NOT ADJUDICATE. A bare "the number appears in the PDF"
    can be a coincidence on a page full of figures; the profit-row context printed alongside is
    what a human reads before anything reaches a heal ledger (§58, and _bse_comparative_rev's
    measured 4-of-12 auto-parse survival rate).

OUT: scripts/_vintage108_docs.json   (resumable; keyed SYM|qe)
RUN: python3 scripts/vintage108_documents.py --cells SYM|QE,SYM|QE [--limit N]
     python3 scripts/vintage108_documents.py --from-class vintage-candidate [--limit N]
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

SCAN = os.path.join(HERE, "_vintage108_scan.json")
ADJ = os.path.join(HERE, "_vintage108_adjud.json")
OUT = os.path.join(HERE, "_vintage108_docs.json")
PDFDIR = os.path.join(HERE, "_vintage108_pdfs")

SCALES = (("crore", 1.0), ("million", 10.0), ("lakh", 100.0), ("thousand", 10000.0))

# fetch_insurers.is_result_filing is shared by ~10 callers and its NEWSSUB veto ("press release",
# "intimation", ...) is applied BEFORE the results hit, so BSE's own wording
#   "Financial Results with Results Press Release & Limited Review Report"  (SYNGENE 2016-01-21)
# is vetoed — the one document that holds the quarter. The row that survives the filter for that
# date carries NO attachment, so the quarter reads as "no filing" (a silent, permanent miss).
# This tool needs the WIDER net and must not widen the shared helper under ~10 other callers
# (memory: feedback-shared-helper-strictest-precondition), so it filters locally:
# the SUBCATNAME is decisive, and the veto only speaks when no results phrase is present.
_SUBCAT_OK = {"financial results", "limited review report", "board meeting", "result", "results"}
_HIT = re.compile(
    r"(financial result|outcome of board meeting|board meeting outcome"
    r"|(?:un)?audited.*result|limited review)",
    re.IGNORECASE,
)
_VETO = re.compile(
    r"(xbrl|investor presentation|earnings call|transcript|newspaper|analyst"
    r"|audio|postal|agm|annual report|allotment|scrutiniz)",
    re.IGNORECASE,
)


def result_filings(o, code, lo, hi):
    """[(ann_yyyymmdd, attachment, subject)] — every announcement in the window that could carry
    the results table. Wider than the shared helper on purpose; see the note above."""
    out = []
    for pg in range(1, 4):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%s&strSearch=P&strToDate=%s&strType=C" % (pg, lo, code, hi)
        )
        try:
            rows = json.loads(FI.bse_get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            if not r.get("ATTACHMENTNAME"):
                continue
            sub = (r.get("SUBCATNAME") or "").strip().lower()
            blob = sub + " " + (r.get("NEWSSUB") or "")
            ok = sub in _SUBCAT_OK or (_HIT.search(blob) and not _VETO.search(blob))
            if not ok:
                continue
            a = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
            out.append((int(a) if a else 0, r["ATTACHMENTNAME"], r.get("NEWSSUB", "") or ""))
        if len(rows) < 50:
            break
    return sorted(set(out), reverse=True)


PROFIT = re.compile(
    r"net\s+profit|profit\s*(/|\(|\s)*\s*\(?loss\)?\s+(for|after)|"
    r"profit\s+after\s+tax|profit\s+for\s+the\s+period",
    re.IGNORECASE,
)
NUMTOK = re.compile(r"-?\(?\d[\d,]*\.?\d*\)?")


def dstr(qe, plus):
    d = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100) + datetime.timedelta(days=plus)
    return d.strftime("%Y%m%d")


def plus_year(qe):
    return qe + 10000


def numbers_on_profit_rows(pdf):
    """[(row_text, [numbers])] for every line whose label looks like a profit line."""
    out = []
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return out
    for page in doc:
        try:
            txt = page.get_text("text")
        except Exception:
            continue
        for line in txt.splitlines():
            if not PROFIT.search(line):
                continue
            nums = []
            for t in NUMTOK.findall(line):
                neg = t.startswith(("(", "-"))
                try:
                    v = float(t.strip("()-").replace(",", ""))
                except ValueError:
                    continue
                nums.append(-v if neg else v)
            if nums:
                out.append((re.sub(r"\s+", " ", line).strip()[:140], nums))
    return out


def full_text(pdf):
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
        return "\n".join(p.get_text("text") for p in doc)
    except Exception:
        return ""


def appears(text, value_cr):
    """Which printed scale (if any) shows `value_cr`, as a STANDALONE token of >=3 digits.

    A substring test at crore scale matched "67" and "59" anywhere on a page of figures — the
    detector fired on SYNGENE's Jan-2017 board-meeting notice, which holds neither number
    (DETECT != CONFIRM). Three significant digits plus token boundaries is the cheapest way to
    make a hit mean something; it also means small-value cells (<1 cr at every scale) simply
    report no hit rather than a coincidence.
    """
    hits = []
    for name, mult in SCALES:
        v = abs(value_cr) * mult
        for dp in (0, 1, 2):
            s = "{:,.{}f}".format(v, dp)
            if len(re.sub(r"[^0-9]", "", s)) < 3:
                continue
            if re.search(r"(?<![\d.,])" + re.escape(s) + r"(?![\d,])", text):
                hits.append(f"{name}:{s}")
                break
    return hits


def one(o, sym, code, qe, stored, detres):
    rec = {"sym": sym, "qe": qe, "scrip": code, "stored": stored, "detres": detres, "filings": {}}
    for tag, target in (("original", qe), ("year_later", plus_year(qe))):
        lo, hi = dstr(target, 8), dstr(target, 150)
        try:
            anns = result_filings(o, code, lo, hi)
        except Exception as ex:
            rec["filings"][tag] = {"err": f"datebound {type(ex).__name__}"}
            continue
        got = []
        for ann_dt, att, sub in anns[:6]:
            pdf = FI.fetch_pdf(o, att)
            if not pdf:
                got.append({"ann": ann_dt, "att": att, "sub": sub[:90], "pdf": "unreachable"})
                continue
            os.makedirs(PDFDIR, exist_ok=True)
            open(os.path.join(PDFDIR, "%s_%d_%s" % (sym, target, att[-40:])), "wb").write(pdf)
            txt = full_text(pdf)
            got.append(
                {
                    "ann": ann_dt,
                    "att": att,
                    "sub": sub[:90],
                    "pages_text_chars": len(txt),
                    "stored_appears": appears(txt, stored),
                    "detres_appears": appears(txt, detres) if detres is not None else [],
                    "profit_rows": numbers_on_profit_rows(pdf)[:12],
                }
            )
        rec["filings"][tag] = {"window": [lo, hi], "n_result_filings": len(anns), "docs": got}
    return rec


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    scan = json.load(open(SCAN, encoding="utf-8"))["cells"]
    targets = []
    if "--cells" in args:
        for tok in args[args.index("--cells") + 1].split(","):
            targets.append(tok.strip())
    elif "--from-class" in args:
        want = args[args.index("--from-class") + 1].split("|")
        adj = json.load(open(ADJ, encoding="utf-8"))["syms"]
        for sym, r in sorted(adj.items()):
            if r.get("proposed") in want:
                targets += [f"{sym}|{q}" for q in sorted(r["cells"])]
    else:
        print(__doc__)
        return

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    todo = [t for t in targets if t not in out][:limit]
    print("document adjudication: %d cells (%d already done)" % (len(todo), len(targets) - len(todo)))
    o = FI.bse_session()
    for _i, key in enumerate(todo, 1):
        c = scan.get(key)
        if not c or c.get("state") != "done":
            print(f"  skip {key} — not in the scan ledger")
            continue
        out[key] = one(o, c["sym"], c["scrip"], c["qe"], c["stored"], c.get("detres"))
        f = out[key]["filings"]
        print(
            "  %-22s original=%s year_later=%s"
            % (
                key,
                sum(1 for d in (f.get("original", {}).get("docs") or []) if d.get("detres_appears")),
                sum(1 for d in (f.get("year_later", {}).get("docs") or []) if d.get("stored_appears")),
            )
        )
        json.dump(out, open(OUT, "w"), indent=1)
    print("done")


if __name__ == "__main__":
    main()
