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
"""FILL-2020: standalone REVENUE 2015-2019 residue, from the NSE archive.

The 58 cells the BSE detres route (fill_std_rev_detres.py) could not land: 19 had no detres row for
the quarter, 13 failed the PAT anchor because the as-filed IGAAP page disagreed with our Ind-AS
restated series, 6 had no revenue row, 1 negative, 3 had no stored PAT to gate against. A different
source can succeed where detres has no row at all, so those get one honest second attempt here.

⚠️ SCOPE. Strictly quarters <= 2019-12. The post-2020 standalone-revenue residue (72 cells,
WESTLIFE/SHRIRAMCIT/EMBDL...) belongs to a concurrently running session; touching it here would
duplicate work and fight over the same two JSON files.

ANCHOR (§42's landing rule, same shape as the detres pass): the page's own PAT must reproduce our
STORED std PAT for that (sym, qe) within max(2cr, 3%) before its revenue is read. Revenue is the
gap and has no anchor of its own, but standalone PAT is stored for nearly all of these cells --
that is precisely why they are revenue-only gaps. A mis-scaled, mis-periodised or wrong-company
page cannot match a stored PAT by accident.

Anti-poison, from §53b: declared basis must read Non-Consolidated, Period Ended must equal the
target quarter, Symbol must be among the era spellings, and CUMULATIVE pages are refused (they are
year-to-date, so a Q2/Q3/Q4 cumulative row would land 6/9/12 months as a quarter).

BANK FORMAT. Many of these are banks/NBFCs (UJJIVAN, KOTAKBANK, LTF, MANAPPURAM, ICICIBANK,
IDFCFIRSTB, INDIANB, IIFL, JMFINANCIL...). The archive DECLARES "Banking"/"Non Banking", so the
top line is chosen from that rather than guessed: banks have no "revenue from operations" row --
theirs is Interest Earned (§42).

Writes revenue (slot 0) only. Operating profit is deliberately untouched: it is a reconstruction
from expense components and a wrong OPM is a visible site bug.

Run:  python -X utf8 scripts/fill2020_tools/read_std_rev_nse.py [--limit N] [--only SYM,SYM]
      python -X utf8 scripts/fill2020_tools/read_std_rev_nse.py --apply
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

_spec = importlib.util.spec_from_file_location("nar", os.path.join(SCRIPTS, "_nse_archive_revop.py"))
NAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NAR)
NAR.JAR = NAR.BF.nse_jar()

TARGETS = os.path.join(HERE, "_revstd_residue.json")
READS = os.path.join(SCRIPTS, "std_rev_nse_reads.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")

PAT_ABS, PAT_REL = 2.0, 0.03
MAX_QE = 20191231  # hard scope bound -- post-2020 is another session's

R_PAT = (
    re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE),
    re.compile(r"net profit\s*/?\s*\(?\s*loss\s*\)?\s*for the period", re.IGNORECASE),
    re.compile(r"net profit\s*\(\+\)\s*/?\s*\(?loss", re.IGNORECASE),
    re.compile(r"profit\s*/?\s*\(?\s*loss\s*\)?\s*(?:from ordinary activities )?after tax", re.IGNORECASE),
)
R_REV_IND = (
    re.compile(r"total income from operations", re.IGNORECASE),
    re.compile(r"net sales\s*/\s*income from operations", re.IGNORECASE),
    re.compile(r"^revenue from operations", re.IGNORECASE),
    re.compile(r"net sales\s*/\s*revenue from operations", re.IGNORECASE),
    re.compile(r"income from operations", re.IGNORECASE),
)
R_REV_BANK = (
    re.compile(r"^interest earned", re.IGNORECASE),
    re.compile(r"total income from operations", re.IGNORECASE),
    re.compile(r"^total income", re.IGNORECASE),
)


def std_link(sym, qe, cache):
    if sym not in cache:
        try:
            cache[sym] = NAR.list_rows(sym)
        except Exception:
            cache[sym] = []
        time.sleep(0.5)
    for row in cache[sym]:
        if (row.get("consolidated") or "").strip().lower().startswith("non"):
            if NAR.iso_qe(row.get("toDate") or "") == qe and row.get("resultDetailedDataLink"):
                return row["resultDetailedDataLink"]
    return None


def read_std(link, sym, qe):
    path = os.path.join(CACHE, "srev_%s_%d_s.html" % (sym.replace("&", "_"), qe))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, f"fetch:{type(ex).__name__}"
    meta, rows = NAR.parse_detail(html)
    basis = (meta.get("Consolidated / Non-Consolidated") or "").strip().lower()
    if not basis.startswith("non"):
        return None, "basis=%s" % (basis or "?")
    if NAR.iso_qe(meta.get("Period Ended", "")) != qe:
        return None, "period={}".format(meta.get("Period Ended"))
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym, *NAR.aliases(sym)])}:
        return None, "symbol={}".format(meta.get("Symbol"))
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.IGNORECASE)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return None, "cumulative-page(YTD)"
    pat = NAR.pick(rows, *R_PAT)
    if pat is None:
        return None, "no-pat-row"
    isbank = meta.get("fmt") == "Banking"
    # A PRINTED 0.00 IS A BLANK ROW, NOT A RESULT. These filings carry the full template and leave
    # the rows they do not use empty: UJJIVAN (a bank) files bank-format, so the industrial
    # "income from operations" row is present and zero, and picking by declared format alone
    # returned rev=0.00 for 6 cells that all passed the PAT anchor perfectly. Take the first
    # NON-ZERO candidate from either row set, and refuse when every candidate is zero -- a company
    # with a stored PAT does not have exactly zero revenue.
    order = (R_REV_BANK, R_REV_IND) if isbank else (R_REV_IND, R_REV_BANK)
    rev = None
    for group in order:
        for pat_re in group:
            v = NAR.pick(rows, pat_re)
            if v is not None and abs(v) > 1e-9:
                rev = v
                break
        if rev is not None:
            break
    if rev is None:
        return None, "no-revenue-row(or all-zero/blank template)"
    return (pat, rev, "bank" if isbank else "industrial"), "ok"


def main():
    args = sys.argv[1:]
    if "--apply" in args:
        return apply_reads()
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    targets = json.load(open(TARGETS))
    fund = json.load(open(FUND))
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    os.makedirs(CACHE, exist_ok=True)
    lc = {}

    work = []
    for sym, qes in sorted(targets.items()):
        if only and sym not in only:
            continue
        for qe in sorted(qes):
            if qe > MAX_QE or "%s|%d" % (sym, qe) in reads:
                continue
            work.append((sym, qe))
    if limit:
        work = work[:limit]
    print("standalone-revenue reads to attempt: %d" % len(work), flush=True)

    ok = skip = 0
    for sym, qe in work:
        row = {r[0]: r for r in fund.get(sym, [])}.get(qe)
        stored = row[1] if row else None
        if stored is None:
            reads["%s|%d" % (sym, qe)] = {"skip": "no-stored-std-pat-anchor"}
            skip += 1
            print("  SKIP %-12s %d  no stored PAT to anchor" % (sym, qe), flush=True)
            continue
        link = std_link(sym, qe, lc)
        if not link:
            reads["%s|%d" % (sym, qe)] = {"skip": "no-nse-std-filing"}
            skip += 1
            print("  SKIP %-12s %d  no NSE standalone filing" % (sym, qe), flush=True)
            continue
        got, why = read_std(link, sym, qe)
        time.sleep(0.7)
        if got is None:
            reads["%s|%d" % (sym, qe)] = {"skip": why}
            skip += 1
            print("  SKIP %-12s %d  %s" % (sym, qe, why), flush=True)
            continue
        pat, rev, fmt = got
        d = abs(pat - stored)
        if d > max(PAT_ABS, abs(stored) * PAT_REL):
            reads["%s|%d" % (sym, qe)] = {"skip": f"pat-anchor off {d:.2f} (page {pat:.2f} vs stored {stored:.2f})"}
            skip += 1
            print("  SKIP %-12s %d  anchor off %.2f (page %.2f vs stored %.2f)" % (sym, qe, d, pat, stored), flush=True)
            continue
        if rev is None or rev < 0:
            reads["%s|%d" % (sym, qe)] = {"skip": "negative-or-missing-revenue"}
            skip += 1
            continue
        reads["%s|%d" % (sym, qe)] = {
            "revS": round(rev, 2),
            "anchor_pat": stored,
            "page_pat": round(pat, 2),
            "fmt": fmt,
            "link": link,
        }
        ok += 1
        print("  OK   %-12s %d  rev=%-12.2f (%s; PAT anchor %.2f cr)" % (sym, qe, rev, fmt, d), flush=True)
        json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    print("\nlanded %d | skipped %d -> %s" % (ok, skip, os.path.basename(READS)))
    return None


def apply_reads():
    reads = json.load(open(READS))
    good = {k: v for k, v in reads.items() if "revS" in v and not v.get("skip")}
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for k, v in good.items():
            sym, qe = k.rsplit("|", 1)
            if int(qe) > MAX_QE:
                continue
            row = d.get(sym, {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            if row[0] is not None:
                continue
            row[0] = v["revS"]
            n += 1
            d[sym][qe] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-30s %d cells" % (os.path.basename(path), n))


if __name__ == "__main__":
    main()
