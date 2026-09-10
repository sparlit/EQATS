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
"""§111i — read the OWNERS-ATTRIBUTABLE consolidated profit off the primary filing PDFs.

THE QUESTION (§111d). Our con slot holds owners-attributable profit. NSE's archive detail page
prints a bottom line called "Net Profit after taxes, minority interest and share of profit of
associates" which does NOT reliably compute it, so the 0fdcc46c4 heals may have moved 52 cells off
the owners' figure. Only the filing settles it.

★ THE READER IS INVERTED, ON PURPOSE. Building a general table parser for 59 filings in 40-odd
house formats is where a reader silently returns a wrong number (§59d is a list of exactly those
accidents: assumed column order, right-edge mismatches, row indices read as data). This dispute does
not need a general parser — it needs to know WHICH of two known candidate values the filing prints
and ON WHICH ROW. So the search runs the other way: for each candidate (the pre-heal store and the
heal), every figure on every consolidated page is tested at each plausible unit scale, and each hit
is reported with its row LABEL, its position in the row, and the row's other figures. A hit on
"Profit attributable to owners of the parent" and a hit on "Profit for the period" are then
adjudicated by what the labels say, not by a column map that had to be guessed.

Guards that stay:
* consolidated pages only — nearest preceding basis heading wins, `standalone` alone flips it back;
* the label is matched BOTH raw and de-spaced, because these PDFs break words ("Ow ners of the
  Parent" in BHARTIARTL's own quarterly report — a pattern anchored on "Owners" finds nothing);
* the COMPREHENSIVE-income block repeats every owners/NCI label, and the y-grid can split
  "Other comprehensive loss for the year attributable to:" across two rows, so `comprehensive` is
  looked for in the preceding rows too, not only in the row that says "attributable to";
* units are read from the page ("Rs. in Lakhs" / "in Million" / "in Crore"), and every scale that
  reproduces a candidate is reported rather than one being picked — a power-of-ten IS one of the
  defect classes here (§74);
* every classified row is also emitted whole, so owners + NCI == total can be checked.

OUT: _vintage111_reads.json   {SYM|qe: {doc: {...}}}
RUN: python3 -X utf8 vintage111_read.py [--only SYM,SYM] [--redo]
"""
import json
import os
import re
import sys
from collections import defaultdict

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.environ.get("V111_WORK", HERE)
DOCS = os.path.join(SP, "_vintage111_docs")
MANI = os.path.join(SP, "_vintage111_docs.json")
DECL = os.path.join(SP, "declined67.json")
OUT = os.path.join(SP, "_vintage111_reads.json")

NUMW = re.compile(r"^\(?-?[\d,]+\.?\d*\)?[*#]?$")
SCALES = (("crore", 1.0), ("lakh", 0.01), ("million", 0.1), ("thousand", 1e-5))

# raw-label patterns
R_OWN = re.compile(
    r"(own\s*ers?|equity\s*holders?|share\s*holders?)\s+of\s+(the\s+)?"
    r"(parent|company|group|corporation)",
    re.IGNORECASE,
)
R_NCI = re.compile(r"non[\s\-]*controlling\s*interest|minority\s*interest", re.IGNORECASE)
R_ATTR = re.compile(r"attributable\s+to", re.IGNORECASE)
R_COMP = re.compile(r"comprehensive", re.IGNORECASE)
R_TOT = re.compile(
    r"(net\s+)?(profit|loss)\s*/?\s*\(?(loss|profit)?\)?\s*"
    r"(for|after)\s+the\s+(period|quarter|year)|profit\s*/?\s*\(?loss\)?\s+after\s+tax"
    r"|profit\s+after\s+tax",
    re.IGNORECASE,
)
R_ASSO = re.compile(r"share\s+of\s+(net\s+)?(profit|loss)", re.IGNORECASE)
R_EPS = re.compile(r"earning[s]?\s+per|\beps\b|face\s+value|paid[\s\-]*up", re.IGNORECASE)
R_BAL = re.compile(r"^\s*(total\s+)?equity\b|other\s+equity|reserves|net\s+worth|share\s+capital", re.IGNORECASE)
# de-spaced variants for PDFs that break words mid-token
D_OWN = re.compile(r"(owners?|equityholders?|shareholders?)of(the)?(parent|company|group)", re.IGNORECASE)
D_NCI = re.compile(r"non-?controllinginterest|minorityinterest", re.IGNORECASE)

# ★ THESE PDFS ARE OFTEN OCR OVER A SCAN, AND OCR MANGLES THE LABEL, NOT THE NUMBER.
# GODREJPROP's Mar-2018 statement carries "Equity hOIdera of Parart" where the filing prints
# "Equity holders of Parent", with 62.59 sitting on it to the paisa. An exact-match pattern throws
# away the one row that answers the question. So the label is ALSO matched fuzzily: canonical
# phrases against every same-length window of the de-punctuated label, with confusable glyphs
# folded first (0/o, 1/l/i, 5/s, 8/b, rn/m). The NUMBER is never fuzzy-matched.
FOLD = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "9": "g", "6": "b", "2": "z"})
CANON_OWN = (
    "ownersoftheparent",
    "ownersofparent",
    "ownersofthecompany",
    "equityholdersofparent",
    "equityholdersoftheparent",
    "shareholdersofthecompany",
    "ownersofthegroup",
)
CANON_EQTY = (
    "equityattributabletoequityholders",
    "equityattributabletoowners",
    "totalequity",
    "otherequity",
    "networth",
    "sharecapital",
)
CANON_NCI = ("noncontrollinginterests", "noncontrollinginterest", "minorityinterest", "minorityinterests")


def fuzzy_has(label, phrases, thresh=0.78):  # 0.78: "Equity hOIdera of Parart" scores
    #                                          0.81, "Total income from operations" 0.44
    """(phrase, ratio) for the best canonical phrase this label contains, fuzzily."""
    import difflib

    t = re.sub(r"[^A-Za-z]", "", label).lower().translate(FOLD).replace("rn", "m")
    # ★ A CAPTION, NOT A SENTENCE. Without a length gate the fuzzy matcher found
    # "owners of the company" inside "...the Board of Directors of the Company at its meeting..."
    # and THOMASCOOK Sep-2016 was then reported HEAL-CORRECT off a row whose only number was the
    # YEAR 2017 (2017 lakh = 20.17 ~ the heal 20.04). A row label that answers this question is a
    # statement caption; prose is never one.
    if len(t) > 46:
        return (None, 0.0)
    best = (None, 0.0)
    for ph in phrases:
        p2 = ph.translate(FOLD).replace("rn", "m")
        n = len(p2)
        for i in range(max(1, len(t) - n + 4)):
            w = t[i : i + n]
            if not w:
                break
            r = difflib.SequenceMatcher(None, p2, w).ratio()
            if r > best[1]:
                best = (ph, r)
    return best if best[1] >= thresh else (None, best[1])


R_UNITS = (
    (re.compile(r"(crores?|crs?\b|\bcr\b)", re.IGNORECASE), "crore"),
    (re.compile(r"(lakhs?|lacs?)", re.IGNORECASE), "lakh"),
    (re.compile(r"(millions?|\bmn\b)", re.IGNORECASE), "million"),
    (re.compile(r"(thousands?|'?000)", re.IGNORECASE), "thousand"),
)
R_CONS = re.compile(r"consolidated", re.IGNORECASE)
R_STAL = re.compile(r"standalone|unconsolidated", re.IGNORECASE)


def tv(w):
    w = w.strip().rstrip("*#").replace(",", "").replace("−", "-")
    neg = w.startswith("(") and w.endswith(")")
    w = w.strip("()")
    try:
        v = float(w)
    except Exception:
        return None
    return -v if neg else v


def unit_of(text):
    """Every unit phrase the page declares, most specific first (a page can name only one)."""
    for rx, nm in R_UNITS:
        m = rx.search(text)
        if m:
            return nm, text[max(0, m.start() - 28) : m.end() + 6].replace("\n", " ")
    return None, None


def page_rows(page, tol=2.6):
    """[(y, label, [values])] for one page, rows clustered by BASELINE PROXIMITY.

    ★ NOT A FIXED GRID. Bucketing y into 3pt cells splits a row whenever the label's baseline and
    its figures' baselines differ by less than a line but fall either side of a bucket edge.
    Measured on COX&KINGS' Mar-2018 statement: the five figures of the owners row sit at y0=319.2
    and the words "a. Owners of the Company" at y0=320.1 — 0.9pt apart, opposite sides of the
    edge at 319.5. The label row came out with no numbers, the figure row with no label, and the one
    row that answers the question vanished. (The NCI row directly below survived only because its
    offset happened not to straddle an edge, which is exactly how this hides.)

    Words are sorted by baseline and grouped while they stay within `tol` of the group's first
    baseline, so a row is held together by how close its glyphs actually are.

    A figure row with no label still borrows the nearest LABEL-ONLY row — and now from either side,
    because a caption can sit a fraction below its own figures as well as above them.
    """
    ws = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
    groups, cur = [], []
    for w in ws:
        if cur and w[1] - cur[0][1] > tol:
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    raw = []
    for g in groups:
        cells = sorted(g, key=lambda w: w[0])
        lab = " ".join(w[4] for w in cells if not NUMW.match(w[4]))
        nums = [tv(w[4]) for w in cells if NUMW.match(w[4]) and tv(w[4]) is not None]
        raw.append((g[0][1], re.sub(r"\s+", " ", lab).strip(), nums))
    out = []
    for i, (y, lab, nums) in enumerate(raw):
        if nums and not lab:
            for j in (i + 1, i - 1):  # look DOWN first, then up
                if 0 <= j < len(raw) and raw[j][1] and not raw[j][2] and abs(raw[j][0] - y) <= 12:
                    lab = raw[j][1] + " \u21b5"
                    break
        out.append((y, lab, nums))
    return out


def classify(rows, i, attr=None):
    """kind, block for row i.

    ★ THE BLOCK IS THE NEAREST `attributable to:` HEADER, not a keyword sweep of nearby rows.
    ADANIENT's Mar-2018 statement prints "Total Comprehensive Income for the period (11+12)" two
    rows ABOVE "Net Profit attributable to :", so a 3-row lookback for the word `comprehensive`
    labelled the PROFIT split as the OCI split — the exact confusion this reader exists to avoid.
    `attr` is (has_comprehensive, row_index) for the last header seen; a row more than 6 rows past
    it is out of any block.
    """
    lab = rows[i][1]
    ds = re.sub(r"[\s.]", "", lab)
    block = ("comprehensive" if attr[0] else "profit") if attr and i - attr[1] <= 6 else "?"
    if R_EPS.search(lab) or R_BAL.search(lab):
        return None, block
    if not R_COMP.search(lab):
        if R_OWN.search(lab) or D_OWN.search(ds):
            return "owners", block
        if R_NCI.search(lab) or D_NCI.search(ds):
            return "nci", block
        # ★ THE BALANCE-SHEET GUARD HAS TO BE FUZZY TOO. R_BAL/R_EQTY reject "Equity attributable
        # to equity holders of the parent" on the raw label, but OCR renders it "Equlty
        # attrlbutable to equity holdsrs ol their parent" — which slips past the raw regex and is
        # then matched by the FUZZY owners pattern, turning a net-worth row into a profit reading.
        # A guard is only as strong as the weakest path into the thing it guards.
        if fuzzy_has(lab, CANON_EQTY, 0.72)[0]:
            return None, block
        ph, _ = fuzzy_has(lab, CANON_OWN)
        if ph:
            return "owners~ocr", block
        ph, _ = fuzzy_has(lab, CANON_NCI)
        if ph:
            return "nci~ocr", block
    if R_ATTR.search(lab):
        return "attr-header", block
    if R_ASSO.search(lab):
        return "associates", block
    if R_TOT.search(lab) and not R_COMP.search(lab):
        return "total", block
    return None, block


def read_doc(path, cands, near_abs=0.35, near_rel=0.006):
    """Locate each candidate value on the CONSOLIDATED pages, and dump the classified rows."""
    doc = fitz.open(path)
    basis = None
    hits, tagged = [], []
    text_pages = 0
    for p in range(len(doc)):
        txt = doc[p].get_text()
        if len(txt) > 400:
            text_pages += 1
        # ★ NO BASIS GATE ON THE ROW THAT MATTERS. A row labelled "attributable to owners of the
        # parent" IS a consolidated row by definition, and gating pages on a `consolidated` keyword
        # threw those rows away wherever the statement's continuation page did not repeat the word,
        # or where the filing prints both bases under one heading. Basis is recorded as an
        # ANNOTATION on every hit and judged per cell instead
        # (memory: feedback-shared-helper-strictest-precondition).
        if R_CONS.search(txt) and not R_STAL.search(txt):
            basis = "con"
        elif R_STAL.search(txt) and not R_CONS.search(txt):
            basis = "std"
        elif R_CONS.search(txt) and R_STAL.search(txt):
            basis = "both"
        unm, uph = unit_of(txt)
        rows = page_rows(doc[p])
        attr, last_total = None, None
        for i, (_y, lab, nums) in enumerate(rows):
            if R_ATTR.search(lab):
                # The y-grid can split "Other comprehensive loss for the year / attributable to:"
                # across two rows, so a header that STARTS with "attributable" borrows the row above
                # for its subject. Borrowing unconditionally is wrong: ADANIENT prints "Total
                # Comprehensive Income for the period" immediately above "Net Profit attributable
                # to :", and that made the profit split read as the OCI split.
                head = lab
                if re.match(r"^attributable\b", lab.strip(), re.IGNORECASE) and i:
                    head = rows[i - 1][1] + " " + lab
                attr = (bool(R_COMP.search(head)), i)
            if not nums:
                continue
            kind, block = classify(rows, i, attr)
            if kind:
                tagged.append(
                    {
                        "page": p,
                        "kind": kind,
                        "block": block,
                        "label": lab[:90],
                        "vals": nums[:8],
                        "unit": unm,
                        "basis": basis,
                    }
                )
            # ★ THE STATEMENT ASSERTS ITS OWN IDENTITY: owners = total - NCI, column by column.
            # Where the owners CAPTION is unreadable (OCR splits "2,670" into "2" and "670", or
            # renders "Equity holders" as "Equity hOIdera") the two rows around it are often clean,
            # and the subtraction recovers the owners figure without trusting any label. MOTHERSON
            # (705.86 - 231.08 = 474.78), VBL (68.94 - 23.86 = 45.08) and TMPV (4336.43 - 40.58 =
            # 4295.85) all fall out of it exactly. Reported as its own kind so it is never confused
            # with a value actually printed on an owners row.
            if kind == "nci" and last_total and len(last_total[1]) == len(nums):
                for sc_nm, sc in SCALES:
                    for ix, (tv_, nv) in enumerate(zip(last_total[1], nums, strict=False)):
                        x = (tv_ - nv) * sc
                        for cname, cval in cands.items():
                            if abs(x - cval) <= max(near_abs, abs(cval) * near_rel):
                                hits.append(
                                    {
                                        "cand": cname,
                                        "cand_val": cval,
                                        "page": p,
                                        "raw": tv_ - nv,
                                        "scale": sc_nm,
                                        "as_cr": round(x, 4),
                                        "ix": ix,
                                        "nvals": len(nums),
                                        "kind": "owners=tot-nci",
                                        "block": block,
                                        "basis": basis,
                                        "label": f"({last_total[0][:40]}) MINUS ({lab[:34]})",
                                        "row": [round(a - b, 4) for a, b in zip(last_total[1], nums, strict=False)][:8],
                                        "page_unit": unm,
                                        "unit_phrase": (uph or "")[:60],
                                    }
                                )
            if kind == "total":
                last_total = (lab, nums)
            for sc_nm, sc in SCALES:
                for ix, v in enumerate(nums):
                    x = v * sc
                    for cname, cval in cands.items():
                        # ★ A CANDIDATE OF 0.0 MATCHES NOISE. With an absolute tolerance, `cval == 0`
                        # accepts every figure in [-0.35, 0.35] — TALWALKARS Mar-2017 (`was` 0.0)
                        # collected 13 "owners" hits, on prose and on a BALANCE-SHEET equity row, and
                        # came out as the only CONTRADICTS in the population. Same family as the
                        # falsy-sentinel defects of §109i/§111b: a zero is not a value to match on.
                        if cval == 0:
                            continue
                        if abs(x - cval) <= max(near_abs, abs(cval) * near_rel):
                            hits.append(
                                {
                                    "cand": cname,
                                    "cand_val": cval,
                                    "page": p,
                                    "raw": v,
                                    "scale": sc_nm,
                                    "as_cr": round(x, 4),
                                    "ix": ix,
                                    "nvals": len(nums),
                                    "kind": kind or "-",
                                    "block": block,
                                    "label": lab[:90],
                                    "row": nums[:8],
                                    "basis": basis,
                                    "page_unit": unm,
                                    "unit_phrase": (uph or "")[:60],
                                }
                            )
    return {"pages": len(doc), "text_pages": text_pages, "hits": hits, "tagged": tagged}


def main():
    only, redo = None, "--redo" in sys.argv
    for i, a in enumerate(sys.argv[1:]):
        if a == "--only":
            only = set(sys.argv[i + 2].split(","))
    # the fetch runs as two workers walking the cell list from both ends, each with its own
    # manifest (DOCS is shared, filenames are unique). Merge, per cell, union of documents.
    mani = {}
    import glob as _g

    for mp in sorted(_g.glob(os.path.join(SP, "_vintage111_docs*.json"))):
        for kk, vv in json.load(open(mp, encoding="utf-8")).items():
            m = mani.setdefault(kk, {"docs": {}})
            m["docs"].update(vv.get("docs", {}))
    sel = json.load(open(DECL, encoding="utf-8"))
    cand = {}
    for v in sel.values():
        if v["fix"]["basis"] == "con":
            cand["{}|{}".format(v["fix"]["sym"], v["fix"]["qe"])] = {
                "store": v["fix"]["was"],
                "heal": v["fix"]["fixed"],
            }
    out = {} if redo else (json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {})
    for key in sorted(mani):
        sym = key.split("|")[0]
        if only and sym not in only:
            continue
        if key not in cand:
            continue
        got = out.setdefault(key, {})
        for fn, meta in sorted(mani[key].get("docs", {}).items()):
            if fn in got and not redo:
                continue
            path = os.path.join(DOCS, fn)
            if not os.path.exists(path):
                got[fn] = {"_err": "not fetched"}
                continue
            try:
                r = read_doc(path, cand[key])
            except Exception as e:
                got[fn] = {"_err": f"{type(e).__name__}: {e}"}
                continue
            r["win"], r["ann"] = meta["win"], meta["ann"]
            got[fn] = r
        ns = sum(1 for d in got.values() for h in d.get("hits", []) if h["cand"] == "store")
        nh = sum(1 for d in got.values() for h in d.get("hits", []) if h["cand"] == "heal")
        print("  %-22s docs=%d  store-hits=%-3d heal-hits=%-3d" % (key, len(got), ns, nh), flush=True)
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    print("DONE %d cells" % len(out))


if __name__ == "__main__":
    main()
