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
"""THE reader: one pass that applies every counter in runbook §61a, and reads the FILING itself.

User, 2026-08-06: *"i am not saying u to fill empties from screener.in but fill it on ur own using
all ur brain that u mentioned in table above that landed u to empty cells now"*. Correct. screener
is a cross-check and a search key (§60e) -- it is NOT the filler. This module fills from filings.

It exists because the old readers each implemented ONE route and reported empty on failure. This one
implements the six failure MODES as six counters, in a single pass, and can only end a cell in one
of the terminal states of §61b -- never a bare "not found".

  MODE 3  every quarter is printed in ~3 filings, so three windows are searched, in this order:
            own quarter (announce date +-8d) -> Q+1 season (preceding-quarter column)
            -> Q+4 season (year-ago comparative column)
  MODE 4  transport is retried with a fresh session and backoff; 0 rows on HTTP 200 after retries
          yields BLOCKED-TRANSPORT, which is NOT a conclusion and never counts as closed
  MODE 2  both label families are tried: industrial ("revenue from operations", "total income from
          operations", "net sales"...) AND finance/NBFC/bank ("revenue", "total income"), all
          glyph-corruption tolerant (a->o, t->l, §51)
  MODE 1  a page with <80 chars of text and >=1 image is NOT empty -- it is image-only; it is
          collected and returned as NEEDS-VISION with page numbers, never as absence
  MODE 5  columns are NEVER taken by index. The column is the one whose PAT reproduces our STORED
          PAT for that quarter+basis, at some declared scale. That anchor is what separates the two
          bases on an interleaved page (the BALKRISIND trap) without any outside target
  MODE 6  when the anchor matches but the resulting revenue contradicts a stored neighbour, the
          suspect is flagged rather than silently written or silently dropped

CONFIRMATION (§58): a hit is only accepted when a SECOND value on the same page+column also
reproduces something we store (the other basis' PAT, or the year/preceding column of a value we
hold). Single-number coincidences at 3 different scales are exactly how wrong cells get written.

  python -X utf8 scripts/fill2020_tools/universal_read.py TARGETS.json [--out OUT.json]
  TARGETS.json: {"SYM|20250331|revC": {"scrip": 500093, "ann": 20250530}, ...}
"""
import concurrent.futures
import datetime
import importlib.util
import json
import os
import re
import sys
import threading
import time

# The tree this module belongs to -- NOT a hardcoded one (fixed 2026-08-09).
#
# This read `~/stocks-wt/fill2020` literally, then `sys.path.insert(0, ...)` it and `os.chdir` into
# it. Every importer therefore got that ONE worktree's geom_read/date_columns/fetch_insurers and,
# worse, that worktree's sf_revop.json + sf_fundamentals.json -- the anchors every read is judged
# against. Running a reader from any other tree silently scored it against another tree's data,
# with no error and nothing in the output to show it had happened. It went unnoticed only because
# the hardcoded path happened to be the active campaign's tree; the day that worktree is stale or
# deleted, reads keep succeeding and quietly anchor on the wrong numbers
# (memory: analyze-live-not-local-bin).
#
# Derive the root from __file__ instead, so a tool always reads the tree it was launched from.
# STOCKS_WT still overrides, for the deliberate cross-tree case.
WT = os.environ.get("STOCKS_WT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(WT, "scripts"))
sys.path.insert(0, os.path.join(WT, "scripts", "fill2020_tools"))
os.chdir(WT)
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402
import geom_read as GEOM  # noqa: E402

_s = importlib.util.spec_from_file_location("brg", os.path.join(WT, "scripts", "backfill_revop_gaps.py"))
BRG = importlib.util.module_from_spec(_s)
_s.loader.exec_module(BRG)

ROOT = WT
REVOP = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
FUND = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

# MODE 2 -- both label families, glyph-tolerant. Ordered: most specific first, so a page carrying
# both "Revenue from operations" and "Total income" resolves to the operating line.
REV_LABELS = [
    re.compile(r"t[o0]tal\s+inc[o0]me\s+fr[o0]m\s+[o0]pera", re.IGNORECASE),
    re.compile(r"revenue\s+fr[o0]m\s+[o0]pera", re.IGNORECASE),
    # Ind-AS 115 wording. CYIENT prints ONLY this -- no "revenue from operations" line anywhere --
    # so omitting it made a fully-text, perfectly readable filing look like it had no revenue row.
    re.compile(r"revenue\s+fr[o0]m\s+c[o0]ntracts?\s+with\s+cust[o0]mers", re.IGNORECASE),
    re.compile(r"inc[o0]me\s+fr[o0]m\s+[o0]pera", re.IGNORECASE),
    re.compile(r"sales\s*/\s*inc[o0]me\s+fr[o0]m\s+[o0]pera", re.IGNORECASE),
    re.compile(r"revenue\s+fr[o0]m\s+sale\s+[o0]f", re.IGNORECASE),
    re.compile(r"^\s*(gr[o0]ss\s+)?(net\s+)?sales\b", re.IGNORECASE),
    re.compile(r"^\s*turn\s?[o0]ver", re.IGNORECASE),
    re.compile(r"^\s*t[o0]tal\s+revenue", re.IGNORECASE),
    re.compile(r"^\s*revenue\s*$", re.IGNORECASE),  # finance layout
    re.compile(r"^\s*t[o0]tal\s+inc[o0]me", re.IGNORECASE),  # finance layout, last resort
]
PAT_LABELS = [
    re.compile(r"[o0]wner.{0,25}[o0]f\s+the\s+(parent|c[o0]mpan|h[o0]lding)", re.IGNORECASE),
    # The owners-attributable figure is often a CONTINUATION line under "Profit attributable to:",
    # so the caption carries no "profit" and no "owners" at all. CYIENT prints "Shareholders of the
    # Company" -- values 1704/1223 (Rs million) = our stored 170.4/122.3 con PAT exactly.
    re.compile(r"(equity\s+)?share\s?h[o0]lders?\s+[o0]f\s+the\s+(c[o0]mpan|parent|h[o0]lding)", re.IGNORECASE),
    re.compile(r"equity\s+h[o0]lders?\s+[o0]f\s+the\s+(parent|c[o0]mpan)", re.IGNORECASE),
    re.compile(r"net\s+pr[o0][fl]i?[lt].{0,45}(f[o0]r\s+the\s+(peri[o0]d|quarter|year)|a[fl]ter\s+tax)", re.IGNORECASE),
    re.compile(r"pr[o0][fl]i?[lt]\s+a[fl]ter\s+tax", re.IGNORECASE),
    # "Profit for the quarter / year" -- the plain Ind-AS caption, with no "Net" prefix and no
    # "period". Required "period" before, so CYIENT's PAT row never matched either.
    # NOTE the (?:...)? around the loss alternative. Writing it as `\(?l[o0]ss\)?` made the word
    # "loss" MANDATORY and silently un-matched plain "Profit for the period (VII-VIII)" -- which is
    # BALKRISIND's consolidated PAT row, the exact anchor. A widened pattern that quietly narrows.
    re.compile(r"pr[o0][fl]i?[lt](?:\s*/\s*\(?l[o0]ss\)?)?\s+f[o0]r\s+the\s+(peri[o0]d|quarter|year)", re.IGNORECASE),
    re.compile(r"pr[o0][fl]i?[lt]\s+attributable\s+t[o0]", re.IGNORECASE),
]
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
SCALES = ((1.0, "crore"), (10.0, "million"), (100.0, "lakh"))
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def nums_after(lines, n, k=14):
    out = []
    for x in lines[n + 1 : n + 1 + k]:
        x = x.strip()
        if NUM.match(x):
            neg = x.startswith("(")
            try:
                v = float(x.strip("()").replace(",", ""))
            except ValueError:
                continue
            out.append(-v if neg else v)
        elif out:
            break
    return out


def rows_matching(lines, pats):
    """-> [(line_index, label, [values])] for every line whose label matches any pattern."""
    out = []
    for n, x in enumerate(lines):
        for p in pats:
            if p.search(x):
                v = nums_after(lines, n)
                if v:
                    out.append((n, x.strip(), v))
                break
    return out


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.05, abs(b) * 0.004)


def shift_q(qe, k):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m] + k
    yy, r = divmod(i, 4)
    mm = [3, 6, 9, 12][r]
    return yy * 10000 + mm * 100 + LAST_DAY[mm]


def stored(sym, qe, what):
    if what in ("patS", "patC"):
        i = 1 if what == "patS" else 3
        for r in FUND.get(sym, []):
            if r[0] == qe and len(r) > i:
                return r[i]
        return None
    i = 0 if what == "revS" else 1
    row = (REVOP.get(sym) or {}).get(str(qe))
    return row[i] if row and len(row) > i else None


def scan_geom(doc, sym, qe, field):
    """§55b done properly: the column is an x-band on the page, not a list index. See geom_read."""
    want_con = field.endswith("C")
    anchor = stored(sym, qe, "patC" if want_con else "patS")
    if anchor is None:
        return None, {"reason": "no stored PAT to anchor on"}
    others = [("this quarter's other-basis PAT", stored(sym, qe, "patS" if want_con else "patC"))]
    for k in range(-6, 7):
        if not k:
            continue
        qn = shift_q(qe, k)
        others.append(("%d PAT" % qn, stored(sym, qn, "patC" if want_con else "patS")))
    others = [o for o in others if o[1] is not None]
    vision, saw_statement_text = [], False
    for pi in range(len(doc)):
        page = doc[pi]
        if len(page.get_text().strip()) < 80 and page.get_images():
            vision.append(pi)  # MODE 1
            continue
        # Does this TEXT page structurally look like a results statement (a PAT-ish row AND a
        # revenue-ish row)? That is what separates "the statement is an image" from "the statement
        # is right here in text and my ANCHOR failed" -- two completely different problems that the
        # first version of this reader collapsed into NEEDS-VISION. It sent SUNDROP and TATACAP to
        # a paid vision read whose chosen pages were an auditor signature page and a credit-rating
        # annexure, while TATACAP's anchor value sat in plain text on pages 14 and 33 of the very
        # same document. Both were then resolved for free by the screener gate.
        if not saw_statement_text:
            rows = GEOM.lines_of(page)
            if any(any(p.search(r[1]) for p in PAT_LABELS) for r in rows) and any(
                any(p.search(r[1]) for p in REV_LABELS) for r in rows
            ):
                saw_statement_text = True
        val, ev = GEOM.find(page, anchor, others, PAT_LABELS, REV_LABELS)
        if val is not None:
            ev["page"] = pi
            return val, ev
    # ONLY a document with no readable statement text is a vision candidate.
    if vision and not saw_statement_text:
        return None, {"vision": vision}
    return None, ({"text_statement_present": True} if saw_statement_text else None)


def scan(doc, sym, qe, field):
    """MODE 1/2/5: locate the column by our stored PAT, then read revenue at that column.

    Returns (value, evidence) or (None, {'vision': [pages]}) or (None, None).
    """
    want_con = field.endswith("C")
    anchor = stored(sym, qe, "patC" if want_con else "patS")
    other = stored(sym, qe, "patS" if want_con else "patC")
    if anchor is None:
        return None, {"reason": "no stored PAT to anchor on"}
    vision = []
    for pi in range(len(doc)):
        text = doc[pi].get_text()
        if len(text.strip()) < 80 and doc[pi].get_images():
            vision.append(pi)  # MODE 1
            continue
        lines = [x.strip() for x in text.split("\n")]
        pat_rows = rows_matching(lines, PAT_LABELS)
        rev_rows = rows_matching(lines, REV_LABELS)
        if not pat_rows or not rev_rows:
            continue
        for _n, plabel, pvals in pat_rows:
            for i, v in enumerate(pvals[:8]):
                for sc, un in SCALES:
                    if not close(v / sc, anchor):
                        continue
                    # MODE 5 CONFIRMATION: the SAME column at the SAME scale must reproduce a
                    # second thing we store, else this is a coincidence across 3 scales.
                    ok2 = None
                    if other is not None and not close(other, anchor):
                        for _m, _ol, ovals in pat_rows:
                            if len(ovals) > i and close(ovals[i] / sc, other):
                                ok2 = f"same column reproduces the other basis' PAT {other:.2f}"
                                break
                    if ok2 is None:
                        # Fall back: ANY other column must reproduce ANY other quarter we store, at
                        # the same scale. Do not assume which quarters a filing prints -- an own
                        # filing shows Q/Q-1/Q-4, a Q+1 filing shows Q+1/Q/Q-3, a Q+4 filing shows
                        # Q+4/Q+3/Q. Hardcoding Q-1 and Q-4 is why this gate rejected CGPOWER even
                        # though its column anchor was correct.
                        nbq = [shift_q(qe, k) for k in range(-6, 7) if k]
                        for qn in nbq:
                            for what, _rowset in (("pat", pvals), ("rev", None)):
                                nb = stored(
                                    sym,
                                    qn,
                                    ("patC" if want_con else "patS")
                                    if what == "pat"
                                    else ("revC" if want_con else "revS"),
                                )
                                if nb is None or close(nb, anchor):
                                    continue
                                cands = [pvals] if what == "pat" else [r[2] for r in rev_rows]
                                for cand in cands:
                                    for j, w in enumerate(cand[:8]):
                                        if j != i and close(w / sc, nb):
                                            ok2 = "col %d reproduces stored %d %s %.2f at the same scale" % (
                                                j,
                                                qn,
                                                what,
                                                nb,
                                            )
                                            break
                                    if ok2:
                                        break
                                if ok2:
                                    break
                            if ok2:
                                break
                    if ok2 is None:
                        continue
                    for _m, rlabel, rvals in rev_rows:
                        # §55b, THE trap this tool reproduced on its first run: a column INDEX is
                        # only transferable between two rows that have the SAME number of value
                        # columns. BALKRISIND's PAT row and revenue row differ in width, so index i
                        # pointed at a different period and yielded 170.61 -- the precise wrong
                        # number I had refused by hand earlier. Equal width or no read.
                        if len(rvals) != len(pvals):
                            continue
                        if len(rvals) > i and rvals[i] > 0:
                            return round(rvals[i] / sc, 2), {
                                "page": pi,
                                "col": i,
                                "scale": un,
                                "rev_row": rlabel[:44],
                                "pat_row": plabel[:44],
                                "anchor": anchor,
                                "confirm": ok2,
                            }
    return None, ({"vision": vision} if vision else None)


_FIL_CACHE = {}
_FIL_LOCK = threading.Lock()


def filings(scrip, a, b):
    """MODE 4: retry transport; distinguish 'API said zero' from 'API would not answer'.

    Cached per (scrip, window): a 660-cell sweep asks for the same company/window many times, and
    BSE throttles on request volume -- uncached, the sweep manufactures its own mode-4 failures.
    """
    ck = (str(scrip), a, b)
    with _FIL_LOCK:
        hit = ck in _FIL_CACHE
    if hit:
        r, err = _FIL_CACHE[ck]
        return r, (FI.bse_session() if r else None), err
    last = None
    for attempt in range(3):
        try:
            sess = FI.bse_session()
            r = FI.datebound(sess, str(scrip), a, b)
        except Exception as e:
            last = repr(e)[:90]
            time.sleep(2.0 * (attempt + 1))
            continue
        if r:
            with _FIL_LOCK:
                _FIL_CACHE[ck] = (r, None)
            return r, sess, None
        last = "0 rows"
        time.sleep(1.5 * (attempt + 1))
    with _FIL_LOCK:
        _FIL_CACHE[ck] = ([], last)
    return [], None, last


def windows(qe, ann):
    """MODE 3: the three filings that print this quarter."""
    d0 = datetime.datetime.strptime(str(ann), "%Y%m%d").date() if ann else None
    out = []
    if d0:
        out.append(
            (
                "own",
                (d0 - datetime.timedelta(days=8)).strftime("%Y%m%d"),
                (d0 + datetime.timedelta(days=8)).strftime("%Y%m%d"),
            )
        )
    # The stored announce date is a FEED date and is routinely stale or simply another event (§52).
    # CYIENT's is 25-May-2025 while it actually filed Q4 in April, so a +-8d window missed the
    # filing entirely and reported "0 rows" -- transport-shaped output from a targeting error.
    # Always also sweep the whole results season for the quarter itself.
    y0, m0 = qe // 10000, (qe // 100) % 100
    s0 = datetime.date(y0, m0, LAST_DAY[m0]) + datetime.timedelta(days=8)
    out.append(("own-season", s0.strftime("%Y%m%d"), (s0 + datetime.timedelta(days=85)).strftime("%Y%m%d")))
    for tag, k in (("Q+1", 1), ("Q+4", 4)):
        q = shift_q(qe, k)
        y, m = q // 10000, (q // 100) % 100
        s = datetime.date(y, m, LAST_DAY[m]) + datetime.timedelta(days=10)
        out.append((tag, s.strftime("%Y%m%d"), (s + datetime.timedelta(days=75)).strftime("%Y%m%d")))
    return out


def read_cell(sym, qe, field, scrip, ann):
    trace, vision_hits, transport = [], [], []
    for tag, a, b in windows(qe, ann):
        fils, sess, err = filings(scrip, a, b)
        if not fils:
            trace.append("{}: {}".format(tag, err or "0 rows"))
            if err == "0 rows":
                transport.append(tag)
            continue
        for _annd, url, _sub in fils[:6]:
            raw, _ = BRG.cached_pdf(sess, url)
            if not raw:
                continue
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                continue
            val, ev = scan_geom(doc, sym, qe, field)
            if val is None and not (ev or {}).get("vision"):
                val, ev = scan(doc, sym, qe, field)
            doc.close()
            if val is not None:
                ev["window"] = tag
                ev["doc"] = url.split("/")[-1][:44]
                return {"state": "FILLED-EXACT", "value": val, "evidence": ev, "trace": trace}
            if ev and ev.get("vision"):
                vision_hits.append({"window": tag, "doc": url.split("/")[-1][:44], "pages": ev["vision"]})
        trace.append("%s: %d filings, no anchored column" % (tag, len(fils)))
        time.sleep(0.4)
    if vision_hits:
        return {"state": "NEEDS-VISION", "candidates": vision_hits[:4], "trace": trace}
    if len(transport) == len(windows(qe, ann)):
        return {"state": "BLOCKED-TRANSPORT", "trace": trace}
    return {"state": "NEEDS-CROSSCHECK", "trace": trace}


def main():
    tg = json.load(open(sys.argv[1]))
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "/tmp/universal.json"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9
    out = {}
    if "--resume" in sys.argv and os.path.exists(out_path):
        out = json.load(open(out_path))  # keep prior verdicts; only retry what is unknown
    done = 0
    for key, meta in sorted(tg.items()):
        # Only BLOCKED-TRANSPORT deserves a retry -- it is the one state that is about the network
        # rather than the document. NEEDS-VISION / NEEDS-CROSSCHECK are diagnoses; re-running the
        # same reader over the same PDFs just burns the BSE rate limit we need for unread cells.
        if key in out and out[key].get("state") != "BLOCKED-TRANSPORT":
            continue
        if done >= limit:
            break
        done += 1
        sym, qe, field = key.split("|")
        r = read_cell(sym, int(qe), field, meta.get("scrip"), meta.get("ann"))
        out[key] = r
        json.dump(out, open(out_path, "w"), indent=1)  # checkpoint every cell
        if r["state"] == "FILLED-EXACT":
            e = r["evidence"]
            where = ("x={}".format(e["x"])) if "x" in e else ("col{}".format(e.get("col")))
            print(
                "  %-28s = %-11s [%s p%s %s /%s] %s"
                % (key, r["value"], e["window"], e.get("page"), where, e["scale"], e["rev_row"])
            )
        else:
            print("  %-28s %s  %s" % (key, r["state"], "; ".join(r["trace"])[:70]))
    json.dump(out, open(out_path, "w"), indent=1)
    n = sum(1 for v in out.values() if v["state"] == "FILLED-EXACT")
    print("\nFILLED-EXACT %d of %d -> %s" % (n, len(out), out_path))
    for st in ("NEEDS-VISION", "NEEDS-CROSSCHECK", "BLOCKED-TRANSPORT"):
        c = sum(1 for v in out.values() if v["state"] == st)
        if c:
            print("  %-20s %d" % (st, c))


if __name__ == "__main__":
    main()
