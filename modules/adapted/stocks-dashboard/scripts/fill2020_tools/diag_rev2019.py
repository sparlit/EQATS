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
"""FILL-2019: DIAGNOSE the 'no-anchor-or-scanned' skips instead of accepting them (§61).

backfill_revop_gaps.py records one undifferentiated reason for every cell whose PDFs it read
without landing a value. That single bucket hides at least six different situations, and each
needs a DIFFERENT next rung:

  no-filing-listed      BSE returned no result announcement in the window  -> widen / §55a retry
  bse-attachment-404    the announcement list HAS the filing but BOTH AttachHis and
                        AttachLive return 404. Measured 2026-08-11: BSE no longer serves
                        PRE-OCT-2018 attachments (Mar/Jun-2018 0 of 6 fetchable, Sep-2018
                        2 of 3, Dec-2018 onward 3 of 3). This is a RETENTION BOUNDARY, not
                        a fetch failure to retry and not something the vision rung can
                        reach — there is no document. Runbook §84.
  scanned-no-text       PDF has no text layer at all                        -> §17b vision / OCR
  no-pl-page            text layer fine, no page carries a revenue row      -> wrong attachment (§55e)
  bank-or-insurer-fmt   pages are BANKISH, this reader refuses them         -> §42/§55 readers
  basis-absent          P&L pages exist but none declares the target basis  -> the con statement
                        genuinely is not in this document (§51a evidence, NOT proof on its own)
  rows-unparsed         page found, extract_rows lost the rev or PAT row    -> reader bug/geometry
  anchor-failed         columns read, none reproduces ANY stored PAT        -> §58d adjudication

It re-uses backfill_revop_gaps' own helpers and its PDF cache, so no read differs from what the
sweep actually did; only the reporting is finer. Network use is the announcement listing only.

Out: scripts/fill2020_tools/_diag_rev2019.json  (per-cell stage + page-level detail)
Run: python -X utf8 scripts/fill2020_tools/diag_rev2019.py [--only SYM,SYM] [--limit N]
"""
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import backfill_revop_gaps as BG  # noqa: E402  (module-level helpers only)
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

BANK_PAGE = BG.re.compile(r"interest\s+earned", BG.re.I)  # §42 bank top line

TARGETS = os.path.join(HERE, "_rev2020_targets.json")
# Per-campaign output: this diagnostic is year-agnostic (it diagnoses whatever _rev2020_targets.json
# currently holds), so `--out <name>` keeps one campaign's per-cell verdicts out of another's file
# and, just as importantly, stops a resume from treating another year's cells as already diagnosed.
OUT = os.path.join(HERE, sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "_diag_rev2019.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
SCRIPS = os.path.join(SCRIPTS, "bse_scrips.json")


def qe_date(qe):
    return datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    # bse_scrips.json "by_id" maps SYMBOL -> scrip code (verified: {"ABB": "500002", ...}). It is
    # built from the LIVE master, so DELISTED names resolve to nothing (§52b) — ALBK, ANDHRABANK,
    # CORPBANK, DHFL... Fall back to _bse_master_all.json, which carries the delisted rows too, and
    # take the code from the master rather than hard-coding a guess.
    name2scrip = {k.upper(): v for k, v in json.load(open(SCRIPS, encoding="utf-8"))["by_id"].items()}
    try:
        for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
            sid = (r.get("scrip_id") or "").upper()
            if sid and sid not in name2scrip and (r.get("Segment") or "Equity") == "Equity":
                name2scrip[sid] = r["SCRIP_CD"]
    except Exception:
        pass
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}

    work = []
    for sym, t in sorted(targets.items()):
        if only and sym not in only:
            continue
        for basis, slot, qes in (("std", 0, t["revS"]), ("con", 1, t["revC"])):
            for qe in qes:
                row = (revop.get(sym) or {}).get(str(qe))
                if row is not None and row[slot] is not None:
                    continue  # already closed
                key = "%s|%d|%s" % (sym, qe, basis)
                if key in out:
                    continue
                work.append((sym, qe, basis, key))
    if limit:
        work = work[:limit]
    print("cells to diagnose: %d" % len(work), flush=True)

    sess = FI.bse_session()
    time.sleep(1)
    pdf_cache = {}  # att -> (has_text, pages_summary)

    for i, (sym, qe, basis, key) in enumerate(work, 1):
        scrip = name2scrip.get(sym.upper())
        if not scrip:
            out[key] = {"stage": "no-bse-scrip"}
            continue
        stored_pat = (fmap.get(sym, {}).get(qe) or [None] * 4)[1 if basis == "std" else 3]
        lo, hi = qe_date(qe) + datetime.timedelta(days=8), qe_date(qe) + datetime.timedelta(days=160)
        try:
            fils = FI.datebound(sess, str(scrip), lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")) or []
        except Exception as ex:
            out[key] = {"stage": "ann-list-error", "err": type(ex).__name__}
            continue
        time.sleep(0.35)
        if not fils:
            out[key] = {"stage": "no-filing-listed", "window": "qe+8d..qe+160d"}
            continue
        stages = []
        pl_pages = con_pages = std_pages = bankish = rowsok = anchorok = 0
        ndocs = ntext = big_docs = 0
        best_cpp = 0.0
        for _annd, att, _sub in fils[:10]:
            if att in pdf_cache:
                raw = pdf_cache[att]
            else:
                raw, _ = BG.cached_pdf(sess, att)
                pdf_cache[att] = raw
            if not raw:
                stages.append("bse-attachment-404")
                continue
            ndocs += 1
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                stages.append("pdf-unopenable")
                continue
            has_text = False
            npages = min(len(doc), 40)
            doc_chars = 0
            for pi in range(npages):
                page = doc[pi]
                text = page.get_text()
                doc_chars += len(text)
                if text.strip():
                    has_text = True
                # A BANK's P&L page has no "revenue from operations" line at all — its top line is
                # Interest Earned (§42). Testing only PL_PAGE labelled every bank cell "no-pl-page",
                # which reads as "the filing has no statement" when in fact the statement is there
                # and the SWEEP is the thing that cannot read it (backfill_revop_gaps requires
                # PL_PAGE and then bails on anything BANKISH, so for a bank the whole PDF route is
                # off by construction). Count those pages as the bank format they are.
                is_bank_page = bool(BANK_PAGE.search(text))
                if not text.strip() or not (BG.PL_PAGE.search(text) or is_bank_page):
                    continue
                pl_pages += 1
                if BG.BANKISH.search(text[:2500]) or is_bank_page:
                    bankish += 1
                    continue
                is_con = bool(BG.CON_HDR.search(text[:1200]))
                is_std = bool(BG.STD_HDR.search(text[:1200]))
                if is_con:
                    con_pages += 1
                if is_std:
                    std_pages += 1
                bases = ["con"] if (is_con and not is_std) else (["std"] if (is_std and not is_con) else ["std", "con"])
                if basis not in bases:
                    continue
                rows = BG.extract_rows(page)
                if "rev" not in rows or ("pat" not in rows and "own" not in rows):
                    continue
                rowsok += 1
                if stored_pat is None:
                    continue
                cand = {
                    q: (fmap.get(sym, {}).get(q) or [None] * 4)[1 if basis == "std" else 3]
                    for q in (qe, BG.prevq(qe), BG.yago(qe), BG.nextq(qe), qe + 10000)
                }
                cand = {q: v for q, v in cand.items() if v is not None}
                if cand and BG.anchor_columns(rows, cand, basis):
                    anchorok += 1
            if has_text:
                ntext += 1
            if npages >= 8:  # plausibly carries a statement
                big_docs += 1
                best_cpp = max(best_cpp, doc_chars / float(npages))
            doc.close()
        # ⚠️ "ANY document had text" is the WRONG test for scannedness, and it mislabelled 8 cells.
        # DLF Mar-2019 lists three result-flagged announcements: a 4-page compliance letter WITH a
        # text layer, and the two that actually matter — "Audited Financial Results" (30 pages) and
        # the Q1 results (24 pages) — with ZERO characters, i.e. pure scans. `ntext > 0` was
        # satisfied by the compliance letter, so the cell reported `no-pl-page` (read as "wrong
        # attachment, fixable by selection") when the truth is "every results document is an image
        # and only the vision rung reaches it". Judge scannedness on the documents that could
        # plausibly CARRY a statement (>=8 pages), by characters per page.
        if ndocs == 0:
            stage = "bse-attachment-404"
        elif ntext == 0 or (big_docs and best_cpp < 600):
            stage = (
                "scanned-no-text"
                if ntext == 0
                else f"scanned-results-docs (best {best_cpp:.0f} chars/page over >=8-page attachments)"
            )
        elif pl_pages == 0:
            stage = "no-pl-page"
        elif bankish and pl_pages == bankish:
            stage = "bank-or-insurer-fmt"
        elif basis == "con" and con_pages == 0:
            stage = "basis-absent(no consolidated P&L page in any listed filing)"
        elif basis == "std" and std_pages == 0 and con_pages:
            stage = "basis-absent(no standalone P&L page)"
        elif rowsok == 0:
            stage = "rows-unparsed"
        elif stored_pat is None:
            stage = "no-stored-pat-anchor"
        elif anchorok == 0:
            stage = "anchor-failed"
        else:
            stage = "anchored-but-not-written(see sweep guards)"
        out[key] = {
            "stage": stage,
            "filings": len(fils),
            "docs": ndocs,
            "text_docs": ntext,
            "pl_pages": pl_pages,
            "con_pages": con_pages,
            "std_pages": std_pages,
            "best_chars_per_page": round(best_cpp, 1),
            "big_docs": big_docs,
            "bankish_pages": bankish,
            "rows_ok": rowsok,
            "anchor_ok": anchorok,
            "stored_pat": stored_pat,
            "notes": sorted(set(stages)),
        }
        print(
            "%-13s %d %-3s  %s (docs %d, PL pages %d, con %d, rows %d, anchor %d)"
            % (sym, qe, basis, stage, ndocs, pl_pages, con_pages, rowsok, anchorok),
            flush=True,
        )
        if i % 20 == 0:
            json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)

    import collections

    c = collections.Counter(v["stage"].split("(")[0] for v in out.values())
    print("\nSTAGE BREAKDOWN")
    for s, n in c.most_common():
        print("%5d  %s" % (n, s))


if __name__ == "__main__":
    main()
