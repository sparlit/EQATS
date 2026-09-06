# -*- coding: utf-8 -*-
"""FILL-2020 rev track: REVENUE for industrial-format filings, read from the BSE filing PDF.

WHY A NEW READER. The residue after the XBRL, identity and detres routes is ~380 cells whose
quarters NSE does not list and BSE's detailed-results JSON has no row for. The only remaining
source is the filing PDF. `backfill_revop_gaps.py` already targets that source and is proven
low-yield here (12 PDFs fetched for ALKYLAMINE, 0 cells); its gap definition also requires BOTH
bases blank, so it cannot even see a con-only gap. This reader instead reuses the machinery the
insurer reader grew, which is strictly better on the two things that actually decide correctness:

  * COLUMN BY PRINTED DATE (runbook §55b). Filings print [current qtr | prev qtr | year-ago | YTD]
    in an order that moves between filers and years, and the same date can head two columns. Every
    figure is slotted under the dated header it sits below, so a column is chosen by the period it
    IS, never by where it happens to sit. This is what stops a year-ago comparative landing in the
    current quarter.
  * OCR FALLBACK (runbook §55d) for scanned or glyph-corrupted text layers, with the Indian
    digit-grouping repair.

GATES — a cell lands only if all hold, else it is skipped WITH a reason:
  P1  the page declares the basis being filled (Standalone / Consolidated), or is unambiguous;
  P2  the column is the one headed with the target quarter-end;
  P3  PAT ANCHOR: that column's profit (owners-attributable where printed) equals our stored PAT
      for (sym, qe, basis) within max(2cr, 3%), under one scale (crore/lakh/million);
  P4  CROSS-BASIS CONTROL, where available: when filling `con` and the standalone revenue is
      already stored, the SAME filing's standalone page must reproduce it within 0.5%. This is the
      insurer reader's A5 and it is what catches a whole-chain misread;
  P5  NEIGHBOUR BAND: within [0.2x, 5x] of the same company's own same-basis revenue nearby;
  P6  DUPLICATE GUARD at apply time: two quarters of one company reporting the same revenue is the
      fingerprint of a column error (runbook §55b) — the batch is refused, not landed.

Revenue ONLY (slot 0/1). Operating profit is deliberately not written: it is a reconstruction from
expense components and a wrong OPM is a visible site bug — same call as fill_std_rev_detres.py.

Run:  python -X utf8 scripts/fill2020_tools/pdf_rev_reader.py [--only SYM,SYM] [--limit N] [--apply]
      [--verify SYM:QE:BASIS]   (positive control: read a cell we ALREADY hold and compare)
"""
import json
import os
import re
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import fitz                                  # noqa: E402
import fetch_insurers as FI                  # noqa: E402
import insurer_con_rev as IC                 # noqa: E402  — page/column/OCR machinery

PDFCACHE = os.path.join(SCRIPTS, "_revgap_pdfcache")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCRIPS = os.path.join(SCRIPTS, "bse_scrips.json")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
FILLS = os.path.join(SCRIPTS, "pdf_rev_reader_fills.json")
SKIPS = os.path.join(SCRIPTS, "_pdf_rev_reader_skips.json")

BAND_LO, BAND_HI = 0.2, 5.0
CTRL_REL = 0.005

# Industrial P&L rows. Every pattern also has a normalised twin (spaces/punctuation stripped) so
# the same regex works on an OCR read — see insurer_con_rev.norm().
# BANK BRANCH (2026-08-11). The reader was BLIND to every bank pack, and the failure was SILENT:
# all 15 open bank cells refused with "no page anchored to stored PAT", which reads exactly like
# "these filings do not carry the numbers". A positive control killed that reading — CANBK
# 20220331 con is a cell we ALREADY HOLD (18226.88) and the reader could not read it either.
# Two label families cause it:
#   * revenue — banks print "Interest Earned (a)+(b)+(c)+(d)", never "Revenue from operations".
#     Our stored bank revenue IS Interest Earned (verified on INDUSINDBK Mar-23: that pack's
#     10,02,071 lakh == stored revS 10020.71, while its Total Income 12,17,431 lakh does not).
#   * PAT — banks print "Net Profit (+) / Loss (-) from Ordinary Activities after Tax"; the old
#     pattern died on the "(+)" and "(-)" glyphs sitting between "Profit" and "Loss".
# Looser labels are safe BY DESIGN here: the PAT anchor, the cross-basis control and the neighbour
# band decide what lands. The reader is allowed to be unreliable because the gates are not.
R_REV = re.compile(r"^revenue from operations|^total revenue from operations"
                   r"|^income from operations|^net sales\s*/\s*income from operations"
                   r"|^interest earned", re.I)
N_REV = re.compile(r"^(total)?revenuefromoperations$|^incomefromoperations$"
                   r"|^netsalesincomefromoperations|^interestearned")
R_PAT_OWN = re.compile(r"owners of the (parent|company)|attributable to.*owners", re.I)
N_PAT_OWN = re.compile(r"ownersofthe(parent|company)|attributableto.*owners")
R_PAT = re.compile(r"^(net\s+)?profit\s*/?\s*\(?loss\)?\s*(for the period|after tax)"
                   r"|^profit\s*/?\s*\(?loss\)?\s*for the period"
                   r"|^net profit[\s\(\)\+\-/]*loss[\s\(\)\+\-/]*"
                   r"(from ordinary activities\s*)?(after tax|for the period)", re.I)
N_PAT = re.compile(r"^(net)?profit(loss)?(fortheperiod|aftertax)"
                   r"|^netprofit.*(aftertax|fortheperiod)")

IC.NORM_OF[id(R_REV)] = N_REV
IC.NORM_OF[id(R_PAT_OWN)] = N_PAT_OWN
IC.NORM_OF[id(R_PAT)] = N_PAT


def cached_pdf(sess, att, sym, qe):
    os.makedirs(PDFCACHE, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", att)[-110:]
    p = os.path.join(PDFCACHE, safe if safe.lower().endswith(".pdf") else safe + ".pdf")
    if os.path.exists(p) and os.path.getsize(p) > 5000:
        return open(p, "rb").read()
    data = FI.fetch_pdf(sess, att)
    if data:
        open(p, "wb").write(data)
    return data


def statements(doc, ocr=False):
    """[(pno, decl, cols, rows)] for pages that carry a revenue row and a dated header."""
    out = []
    for pno in range(min(doc.page_count, IC.OCR_MAX_PAGES if ocr else doc.page_count)):
        try:
            cols = IC.header_columns(doc[pno], ocr)
            if len(cols) < 2:
                continue
            rows = IC.rows_on_columns(doc[pno], cols, ocr)
        except Exception:
            continue
        if IC.pick_row(rows, R_REV) is None:
            continue
        out.append((pno, IC.declared_basis(rows), cols, rows))
    return out


def read_cell(st, qe, stored_pat):
    """(revenue, scale, pat_seen) for the column headed `qe` on this page, or None."""
    pno, decl, cols, rows = st
    k = IC.column_for(cols, qe)                      # P2
    if k is None:
        return None
    rev = IC.at(IC.pick_row(rows, R_REV) or [], k)
    pat_v = IC.at(IC.pick_row(rows, R_PAT_OWN) or [], k)
    if pat_v is None:
        pat_v = IC.at(IC.pick_row(rows, R_PAT) or [], k)
    if rev is None or pat_v is None:
        return None
    for name, div in IC.SCALES:                      # P3 — scale by anchor
        seen = pat_v / div
        if abs(seen - stored_pat) <= max(2.0, 0.03 * max(abs(seen), abs(stored_pat))):
            return round(rev / div, 2), name, round(seen, 2)
    return None


def best_read(doc, qe, basis, stored_pat, ocr=False):
    for st in statements(doc, ocr):
        if st[1] and st[1] != basis:                 # P1
            continue
        got = read_cell(st, qe, stored_pat)
        if got:
            return got + (st[0], "ocr" if ocr else "text")
    return None


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    verify = argv[argv.index("--verify") + 1] if "--verify" in argv else None
    apply_it = "--apply" in argv

    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP_DOCS))
    ledger = json.load(open(REVOP_LEDGER))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    codes = json.load(open(SCRIPS))["by_id"]
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    sess = FI.bse_session()

    def window(qe):
        y, m = qe // 10000, (qe // 100) % 100
        lo = "%04d%02d%02d" % (y + (m + 1) // 12, (m % 12) + 1, 5)
        hm, hy = ((m + 4 - 1) % 12) + 1, y + (m + 4 - 1) // 12
        return lo, "%04d%02d%02d" % (hy, hm, 28)

    def fetch_and_read(sym, qe, basis, stored_pat):
        code = codes.get(sym)
        if not code:
            return None, "no BSE scrip code"
        lo, hi = window(qe)
        anns, _s = IC.anns_with_retry(sess, str(code), lo, hi)
        if not anns:
            return None, "no result filing in %s..%s after 3 tries" % (lo, hi)
        for adate, att, _sub in sorted(anns):
            pdf = cached_pdf(sess, att, sym, qe)
            if not pdf:
                continue
            try:
                doc = fitz.open(stream=pdf, filetype="pdf")
            except Exception:
                continue
            got = best_read(doc, qe, basis, stored_pat)
            if not got:
                got = best_read(doc, qe, basis, stored_pat, ocr=True)
            if got:
                return (got, att, adate, doc), None
        return None, "no page anchored to stored %s PAT" % basis

    # ---- positive control mode -------------------------------------------------------------
    if verify:
        sym, qe_s, basis = verify.split(":")
        qe = int(qe_s)
        stored_pat = (fmap.get(sym, {}).get(qe) or [None, None, None, None])[
            1 if basis == "std" else 3]
        stored_rev = ((revop.get(sym) or {}).get(qe_s) or [None] * 9)[0 if basis == "std" else 1]
        res, why = fetch_and_read(sym, qe, basis, stored_pat)
        if not res:
            print("%s %s %s -> NO READ (%s)" % (sym, qe, basis, why))
            return
        (rev, scale, seen, pno, reader), att, adate, _doc = res
        ok = stored_rev is not None and abs(rev - stored_rev) <= max(1.0, CTRL_REL * abs(stored_rev))
        print("%s %s %s -> read %.2f | stored %s | %s  (p%d, %s, %s, anchor %.2f vs %s)" % (
            sym, qe, basis, rev, stored_rev, "MATCH" if ok else "*** DIFFERS",
            pno, scale, reader, seen, stored_pat))
        return

    syms = sorted(targets) if not only else [s for s in sorted(targets) if s in only]
    if limit:
        syms = syms[:limit]

    nread = 0
    for si, sym in enumerate(syms, 1):
        for basis, fld in (("std", "revS"), ("con", "revC")):
            for qe in targets[sym][fld]:
                key = "%s|%d|%s" % (sym, qe, basis)
                if key in fills:
                    continue
                frow = fmap.get(sym, {}).get(qe) or [None, None, None, None]
                stored_pat = frow[1 if basis == "std" else 3]
                if stored_pat is None:
                    skips[key] = "no stored %s PAT to anchor against" % basis
                    continue
                # §44 AMBIGUITY GUARD. Many filings never print the word "Standalone"/"Consolidated"
                # in a place the reader can see, and when the two bases' stored PATs are within
                # anchor tolerance of each other, one page satisfies BOTH — which is how a
                # standalone page duplicates itself into the con slot (ISEC; TATAELXSI Mar-2024
                # stores 196.93 on both bases). Fill con from such a filing only when the page
                # DECLARES itself consolidated.
                ambiguous = (frow[1] is not None and frow[3] is not None and
                             abs(frow[1] - frow[3]) <= max(2.0, 0.03 * abs(frow[1])))
                res, why = fetch_and_read(sym, qe, basis, stored_pat)
                if not res:
                    skips[key] = why
                    continue
                (rev, scale, seen, pno, reader), att, adate, doc = res
                if basis == "con" and ambiguous:
                    decl_ok = any(st[0] == pno and st[1] == "con"
                                  for st in statements(doc, reader == "ocr"))
                    if not decl_ok:
                        skips[key] = ("std/con PAT indistinguishable (%s vs %s) and page p%d does "
                                      "not declare consolidated — refusing, runbook §44"
                                      % (frow[1], frow[3], pno))
                        continue

                # P4 — cross-basis control
                twin_slot = 0 if basis == "con" else 1
                twin_stored = ((revop.get(sym) or {}).get(str(qe)) or [None] * 9)[twin_slot]
                ctrl = None
                if basis == "con" and twin_stored is not None:
                    tpat = (fmap.get(sym, {}).get(qe) or [None, None])[1]
                    if tpat is not None:
                        c = best_read(doc, qe, "std", tpat) or best_read(doc, qe, "std", tpat, True)
                        ctrl = c[0] if c else None
                    if ctrl is None or abs(ctrl - twin_stored) > max(1.0, CTRL_REL * abs(twin_stored)):
                        skips[key] = "std control failed: filing reads %s against stored %s" % (
                            ctrl, twin_stored)
                        continue

                # P5 — neighbour band
                med = IC_neighbour(revop, sym, qe, basis)
                if med and not (BAND_LO <= rev / med <= BAND_HI):
                    skips[key] = "neighbour-band %.2f (%.2f vs median %.2f)" % (rev / med, rev, med)
                    continue

                fills[key] = {"rev": rev, "basis": basis, "page": pno, "scale": scale,
                              "anchor": seen, "stored_pat": stored_pat, "reader": reader,
                              "std_control": ctrl,
                              "src": "BSE %s (filed %s)" % (att, adate)}
                nread += 1
                print("%-13s %d %-3s rev %-12.2f p%-3d %-7s %-4s anchor %.2f" % (
                    sym, qe, basis, rev, pno, scale, reader, seen), flush=True)
                time.sleep(0.4)
        if si % 5 == 0:
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            print("  [%d/%d] read %d" % (si, len(syms), nread), flush=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    print("\nREAD %d this run (%d ledgered)" % (nread, len(fills)))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched)")
        return

    # P6 — duplicate guard
    by = defaultdict(list)
    for key, v in fills.items():
        s_, q_, b_ = key.split("|")
        by[(s_, b_)].append((q_, v["rev"]))
    dupes = []
    for (s_, b_), items in sorted(by.items()):
        seen_v = {}
        for q_, rev in sorted(items):
            if rev in seen_v:
                dupes.append("%s %s: %s and %s both %.2f" % (s_, b_, seen_v[rev], q_, rev))
            seen_v[rev] = q_
    if dupes:
        print("REFUSING TO APPLY — duplicate revenue across quarters:")
        for d in dupes:
            print("   " + d)
        sys.exit(2)

    applied = 0
    for key, v in sorted(fills.items()):
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None:
            continue
        slot = 0 if basis == "std" else 1
        if row[slot] is None:
            row[slot] = v["rev"]
            applied += 1
            lrow = ledger.setdefault(sym, {}).get(qe_s)
            if lrow is None:
                ledger[sym][qe_s] = list(row)
            elif lrow[slot] is None:
                lrow[slot] = v["rev"]
    json.dump(revop, open(REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(REVOP_LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d revenue cells" % applied)


def IC_neighbour(revop, sym, qe, basis):
    slot = 0 if basis == "std" else 1
    have = [(abs(int(q) - qe), row[slot]) for q, row in (revop.get(sym) or {}).items()
            if row[slot] is not None and int(q) != qe and row[slot] > 0]
    if not have:
        return None
    vals = sorted(v for _, v in sorted(have)[:8])
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


if __name__ == "__main__":
    main()
