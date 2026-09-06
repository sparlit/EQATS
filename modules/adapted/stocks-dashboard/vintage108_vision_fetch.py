# -*- coding: utf-8 -*-
"""VISION RUNG — render the consolidated P&L page for the 12 cells nothing cheaper could settle.

Reached only after the ladder was measured (runbook §112b): XBRL reaches 8 of 143 in this era, the
NSE page's own components reproduce the owners figure on 3 of 8 (failed calibration), and 0 of 4
Mar-2017 filings carry a text layer. These 12 are the cells where the owners reader and the FY-annual
identity give OPPOSITE answers, so only the filing arbitrates. User approved the spend.

WHAT IT DOES: finds the filing for the cell's own quarter (post-quarter stretch qe+8d..qe+150d, never
the stored ann date — §52.1), downloads it through the AnnPdfOpen resolver (pre-Nov-2018 attachments
404 on both bases every other fetcher tries), locates the CONSOLIDATED profit page by scoring each
page's rendered text for consolidated-statement markers, and renders it at 200 dpi for a reader.

⚠️ A RENDER IS NOT A READ. The image is evidence to be read against an ON-PAGE IDENTITY, never a
digit to be trusted on its own (memory: feedback-render-is-not-a-read, feedback-image-detail-reads-
are-guesses). The identities available on a consolidated P&L are:
    profit for the period      == PBT - tax
    owners-attributable        == profit for the period - non-controlling interests
    the four quarters          == the printed year-to-date / annual column
Nothing lands without one of them.

OUT: scripts/_vintage108_vision/<SYM>_<QE>_p<N>.png  + _vintage108_vision_index.json
RUN: python3 scripts/vintage108_vision_fetch.py [--only SYM,SYM]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fetch_insurers as FI  # noqa: E402
import vintage108_documents as D  # noqa: E402
import vintage108_sweep as SW  # noqa: E402
import fitz  # noqa: E402

QUEUE = os.path.join(HERE, "_vintage108_con_filing_queue.json")
OUTDIR = os.path.join(HERE, "_vintage108_vision")
INDEX = os.path.join(HERE, "_vintage108_vision_index.json")
DPI = 200

CON = re.compile(r"consolidated", re.I)
PROFIT = re.compile(r"profit\s*(for the period|after tax|attributable)|"
                    r"non[- ]controlling|minority interest", re.I)
NOT_BS = re.compile(r"balance sheet|assets|equity and liabilities|cash flow", re.I)


NUMTOK = re.compile(r"\d[\d,]*\.\d{2}")


def score_page(page):
    """How likely is this page the RESULTS TABLE? Score on NUMERIC DENSITY, not on prose.

    ★ Ranking by the word "consolidated" picks the auditor's report and the covering letter —
    both of which say it repeatedly and contain no figures — over the statement itself. ASIANTILES
    Mar-2017 rendered pages 5 and 6 (an audit opinion and a compliance declaration) while the
    tables sat on pages 2-3. A results table is dense with `1,234.56` tokens; prose is not.
    """
    try:
        t = page.get_text("text")
    except Exception:
        return 0
    n = len(NUMTOK.findall(t))
    s = n * 4
    if n >= 20:
        s += 8 * len(CON.findall(t)) + 4 * len(PROFIT.findall(t))
    s -= 6 * len(NOT_BS.findall(t))
    return s


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    q = json.load(open(QUEUE, encoding="utf-8"))["p1_identity_contradicts_owners_reader"]
    codes = SW.scrip_map()
    os.makedirs(OUTDIR, exist_ok=True)
    idx = json.load(open(INDEX, encoding="utf-8")) if os.path.exists(INDEX) else {}
    o = FI.bse_session()
    print("P1 cells to render: %d" % len(q))

    for k, rec in sorted(q.items()):
        if k in idx:
            continue
        sym, qe = k.split("|")
        if only and sym not in only:
            continue
        code = codes.get(sym)
        if not code:
            idx[k] = {"err": "no BSE scrip code"}
            print("  %-22s no scrip code" % k)
            continue
        anns = D.result_filings(o, code, D.dstr(int(qe), 8), D.dstr(int(qe), 150))
        best = None
        for ann, att, sub in sorted(anns):          # earliest first = the quarter's own filing
            pdf = FI.fetch_pdf(o, att)
            if not pdf:
                continue
            try:
                doc = fitz.open(stream=pdf, filetype="pdf")
            except Exception:
                continue
            ranked = sorted(((score_page(p), i) for i, p in enumerate(doc)), reverse=True)
            if not ranked or ranked[0][0] <= 0:
                # No text layer at all to rank by — the §75 corrupted-scan class. The statement is
                # near the FRONT (cover letter, then results, then the audit opinion), so take the
                # first pages rather than a middle guess, and let the reader see them.
                ranked = [(0, i) for i in range(min(4, doc.page_count))]
            # ★ PREFER THE QUARTER'S OWN FILING, NOT THE FATTEST PDF. Picking by page count made
            # WOCKPHARMA's Dec-2015 cell resolve against the MAY-2016 annual filing, whose Q3
            # column is a later vintage of the same quarter — the exact thing this campaign exists
            # to remove. `anns` is sorted ascending, so the first one that yields a PDF is the
            # earliest filing in the post-quarter window and is the one to keep.
            if best is None:
                best = (ann, doc, att, ranked, sub)
            if ranked[0][0] > 0:
                break
        if best is None:
            idx[k] = {"err": "no PDF reachable", "n_filings": len(anns)}
            print("  %-22s NO PDF (%d result filings in window)" % (k, len(anns)))
            continue
        ann, doc, att, ranked, sub = best
        pages = [i for _, i in ranked[:3]]
        files = []
        for i in sorted(set(pages)):
            pm = doc[i].get_pixmap(dpi=DPI)
            fp = os.path.join(OUTDIR, "%s_%s_p%d.png" % (sym, qe, i + 1))
            pm.save(fp)
            files.append(os.path.basename(fp))
        best_txt = doc[ranked[0][1]].get_text("text") if ranked else ""
        n_nums = len(NUMTOK.findall(best_txt))
        idx[k] = {"ann": ann, "att": att, "subject": sub[:90], "pages": doc.page_count,
                  "top_page": ranked[0][1] + 1, "top_page_numbers": n_nums,
                  "readable_as_text": n_nums >= 40,
                  "rendered": files, "was": rec["was"], "fixed": rec["fixed"],
                  "identity_implies": rec.get("implied"), "owners_reader": rec.get("owners_value"),
                  "action_if_filing_backs_identity": rec.get("action_if_filing_backs_identity")}
        print("  %-22s ann %s  %2d pages -> %s" % (k, ann, doc.page_count, ", ".join(files)))
        json.dump(idx, open(INDEX, "w"), indent=1)
    json.dump(idx, open(INDEX, "w"), indent=1)
    print("rendered %d cells" % sum(1 for v in idx.values() if v.get("rendered")))


if __name__ == "__main__":
    main()
