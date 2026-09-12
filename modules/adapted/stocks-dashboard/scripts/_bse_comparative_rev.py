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
"""Fill std revenue from the BSE announcement PDF — own-quarter column or, when the filer
RESTATED, the year-later filing's comparative column.

WHY this exists. Two classes the NSE-archive pass cannot close:
  * pat-anchor refusals — the archive page is the AS-ORIGINALLY-FILED result and our stored PAT
    is the RESTATED one, so the anchor correctly refuses. TORNTPOWER Jun-2016 is the worked case:
    the original filing says PAT 30.63, we store 43.70, and the year-later filing's 30.06.2016
    comparative column says 43.70 with revenue 2,583.67. Taking the original filing's revenue
    would have written the wrong vintage beside a restated PAT.
  * never-attempted — NSE serves neither a detail page nor an XBRL for the quarter.

ROUTE. Stored ann date -> BSE AnnSubCategoryGetData in a window -> attachment -> PDF. Attachments
before ~Nov-2018 404 on BOTH bases every fetcher tries; fetch_insurers.fetch_pdf now falls back to
the AnnPdfOpen.aspx resolver, which is what makes the pre-2018 half of this reachable at all.

⚠️ THE AUTO-PARSE IS PROPOSAL-ONLY — DO NOT WRITE ITS OUTPUT UNVERIFIED. Measured 2026-08-24 over
12 auto-reads: only 4 survived a Moneycontrol cross-check. LTF 2019-06 parsed 3,312.77 against MC's
16.56; MFSL 2019-06 parsed 0.22 against 196.13; IRCON 123.84 against 1,215.89. The PAT anchor proves
the COLUMN carries the right PAT — it does NOT prove the revenue-row band picked the right cell in
that column, and on multi-block statements it frequently does not. Every read must be MC-confirmed
or vision-read before it reaches a ledger.

GATE, identical in spirit to every other route here: the column whose PAT equals the STORED PAT
for (sym, qe, std) under one scale (crore/lakh/million) is the column read; no anchor, no write.
A restated cell is anchored against the YEAR-LATER filing's comparative, which is exactly the
vintage our stored PAT came from.

Text-layer PDFs are parsed and gated here. Scanned ones (no text layer at all — common pre-2018)
cannot be parsed and are written to a VISION QUEUE with their rendered pages, for a reader.

Run: python -X utf8 scripts/_bse_comparative_rev.py --cells <json> [--limit N]
     cells = [[SYM, QE], ...]
"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fetch_insurers as FI
import fitz

OUT = os.path.join(HERE, "_bsecomp_reads.json")
VQ = os.path.join(HERE, "_bsecomp_vision_queue.json")
SKIPS = os.path.join(HERE, "_bsecomp_skips.json")
PDFDIR = os.path.join(HERE, "_bsecomp_pdfcache")
os.makedirs(PDFDIR, exist_ok=True)

SCALES = (("crore", 1.0), ("lakh", 100.0), ("million", 10.0))
NUM = re.compile(r"\(?-?[\d,]+\.\d{2}\)?")


def _shift(yyyymmdd, days):
    """Shift a YYYYMMDD stamp by N CALENDAR days.

    ★ Do NOT do this with integer arithmetic. `20180514 - 21` is 20180493 — month 04, day 93 —
    which BSE answers with an EMPTY LIST rather than an error, so every cell reports
    "no-bse-filing-in-either-window" and the run looks like a wall of genuine absences. This
    masqueraded as IP rate-limiting for a whole pass (2026-08-24): a +-7 window happened to stay
    inside a valid month for mid-month announce dates and worked, so WIDENING the window to +-21
    made the tool strictly worse while looking like a fix.
    """
    d = str(yyyymmdd)
    dt = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])) + datetime.timedelta(days=days)
    return dt.strftime("%Y%m%d")


def tonum(s):
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def qe_label_variants(qe):
    y, m, d = int(str(qe)[:4]), int(str(qe)[4:6]), int(str(qe)[6:8])
    mn = ["", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"][m]
    return ("%02d.%s.%d" % (d, mn, y), "%02d/%s/%d" % (d, mn, y), "%02d-%s-%d" % (d, mn, y))


def page_words(pg):
    return pg.get_text("words")  # (x0,y0,x1,y1,word,block,line,wordno)


def column_at(words, xc, tol=26.0):
    """Numbers whose horizontal centre sits within tol of xc, top to bottom."""
    out = []
    for x0, y0, x1, _y1, w, *_ in words:
        if not NUM.fullmatch(w):
            continue
        if abs((x0 + x1) / 2.0 - xc) <= tol:
            out.append((y0, tonum(w)))
    out.sort()
    return [v for _, v in out if v is not None]


def find_anchor_columns(words, target, scale):
    """x-centres of every number equal to target under this scale."""
    hits = []
    for x0, y0, x1, _y1, w, *_ in words:
        if not NUM.fullmatch(w):
            continue
        v = tonum(w)
        if v is None:
            continue
        if abs(v / scale - target) <= max(0.02, abs(target) * 0.005):
            hits.append(((x0 + x1) / 2.0, y0))
    return hits


R_REVLINE = re.compile(r"revenue from operation|net sales|income from operation", re.IGNORECASE)


def revenue_y(pg):
    """(top, bottom) y of the revenue-from-operations label, if present. TWO elements — an
    earlier version indexed ry[3] and died with IndexError on the first PDF that reached it."""
    for _x0, _y0, _x1, _y1, _w, *_ in page_words(pg):
        pass
    txt = pg.get_text()
    if not R_REVLINE.search(txt):
        return None
    for ln in pg.get_text("dict")["blocks"]:
        for l in ln.get("lines", []):
            s = "".join(sp["text"] for sp in l.get("spans", []))
            if R_REVLINE.search(s) and not re.search(r"other operating|total income", s, re.IGNORECASE):
                return l["bbox"][1], l["bbox"][3]
    return None


def try_pdf(path, qe, stored_pat):
    """-> (rev, note) or (None, reason). Anchored: a column carrying stored_pat under one scale,
    and the revenue row read from that same column."""
    doc = fitz.open(path)
    try:
        for pno in range(len(doc)):
            pg = doc[pno]
            txt = pg.get_text()
            if len(txt.strip()) < 40:
                continue
            if not re.search(r"standalone|unconsolidated", txt, re.IGNORECASE):
                continue
            ry = revenue_y(pg)
            if ry is None:
                continue
            words = page_words(pg)
            for sname, sc in SCALES:
                for xc, ay in find_anchor_columns(words, stored_pat, sc):
                    if ay <= ry[1]:
                        continue  # PAT must sit BELOW the revenue row
                    band = [w for w in words if ry[0] - 3 <= w[1] <= ry[1] + 3]
                    for x0, _y0, x1, _y1, w, *_ in band:
                        if not NUM.fullmatch(w):
                            continue
                        if abs((x0 + x1) / 2.0 - xc) <= 26.0:
                            v = tonum(w)
                            if v is None or v / sc <= 0:
                                continue
                            return round(v / sc, 2), "page %d, %s scale, PAT anchor %.2f" % (pno + 1, sname, stored_pat)
        return None, "no anchored standalone column"
    finally:
        doc.close()


def main():
    argv = sys.argv
    cells = json.load(open(argv[argv.index("--cells") + 1]))
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 0
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    # Codes bse_scrips.json lacks, resolved from BSE's own ListofScripData (all statuses) and
    # accepted only when the ISIN ISSUER PREFIX matches NSE's for the same ticker (runbook 95).
    # Full-ISIN equality is too strict — a face-value/series re-issue changes the last digits for
    # the SAME company (ADVANTA INE517H01028 vs INE517H01010) — while the issuer prefix still
    # rejects a recycled ticker (SPSL: BSE INE318K vs the NSE filer's INE298G, a different company).
    _extra = os.path.join(HERE, "_bse_scrips_extra.json")
    if os.path.exists(_extra):
        for k, v in json.load(open(_extra)).items():
            scrips.setdefault(k, v)
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    vq = json.load(open(VQ)) if os.path.exists(VQ) else {}
    skips = {}

    def _flush():
        json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
        json.dump(vq, open(VQ, "w"), indent=1, sort_keys=True)
        json.dump(skips, open(SKIPS, "w"), indent=1, sort_keys=True)

    _flush()  # truncate stale ledgers from a previous run IMMEDIATELY
    # ONE SESSION PER SYMBOL, NOT ONE PER RUN. BSE throttles a reused cookie jar after the first
    # scrip and answers with an EMPTY LIST, not an error — so a loop that shares a session records
    # "no-bse-filing-in-either-window" for every symbol after the first. Measured 2026-08-24:
    # 8 scrips returned 0 rows on a shared session and 2-3 rows each on a fresh one (§57c: an empty
    # BSE list is rate-limiting until proven otherwise).
    o = FI.bse_session()
    _last_sym = [None]

    def _session_for(sym):
        if _last_sym[0] != sym:
            _last_sym[0] = sym
            # 1.5s was not enough: the throttle is IP-level, not per-cookie. A 66-symbol run at
            # 1.5s still returned empty lists for 62 of them while the SAME scrips answered on an
            # unhurried fresh session. Measured 2026-08-24.
            time.sleep(8.0)
            return FI.bse_session()
        return o

    n = 0
    for sym, qe in cells:
        if limit and n >= limit:
            break
        qe = int(qe)
        key = "%s|%d" % (sym, qe)
        if sym in out and str(qe) in out[sym]:
            continue
        code = scrips.get(sym)
        if not code:
            skips[key] = "no-bse-scrip"
            _flush()
            continue
        frow = fmap.get(sym, {}).get(qe)
        if not frow or frow[1] is None:
            skips[key] = "no-stored-std-pat"
            _flush()
            continue
        stored, ann = frow[1], frow[2]
        if not ann:
            skips[key] = "no-ann-date"
            _flush()
            continue
        n += 1
        # TWO windows, in order: this quarter's own filing, then the YEAR-LATER filing whose
        # comparative column carries the RESTATED vintage. The second is what closes the
        # pat-anchor-refusal class — where the original filing's PAT disagrees with what we
        # store, the original's revenue is the wrong vintage too, and only the comparative
        # column is anchored by our stored PAT (TORNTPOWER Jun/Sep-2016, measured).
        yl = fmap.get(sym, {}).get(int(qe) + 10000)  # same quarter, next year
        # +-21d, not +-7: BSE's announcement stream carries the result under the board-meeting
        # outcome whose date can sit well away from our stored announce date (which for old rows
        # is often a qe+45d default, runbook 52). The tight window reported 39 false
        # "no-bse-filing" refusals on the first pass.
        windows = [(_shift(ann, -21), _shift(ann, 21), "own-quarter")]
        if yl and yl[2]:
            windows.append((_shift(yl[2], -21), _shift(yl[2], 21), "year-later-comparative"))
        rows = []
        _sess = _session_for(sym)
        for lo, hi, wname in windows:
            try:
                r = FI.datebound(_sess, str(code), lo, hi)
            except Exception:
                r = []
            rows += [(dt, att, sub, wname) for dt, att, sub in r]
        if not rows:
            skips[key] = "no-bse-filing-in-either-window"
            _flush()
            continue
        got = False
        for _dt, att, sub, wname in rows[:4]:
            p = os.path.join(PDFDIR, "%s_%d_%s" % (sym, qe, att))
            if not os.path.exists(p):
                try:
                    d = FI.fetch_pdf(_sess, att)
                except Exception:
                    d = None
                if not d:
                    continue
                open(p, "wb").write(d)
                time.sleep(0.3)
            # text layer?
            doc = fitz.open(p)
            has_text = any(len(doc[i].get_text().strip()) > 40 for i in range(len(doc)))
            npages = len(doc)
            doc.close()
            if not has_text:
                vq[key] = {
                    "pdf": p,
                    "pages": npages,
                    "stored_pat": stored,
                    "ann": ann,
                    "window": wname,
                    "why": "scanned - no text layer; needs a vision read of the standalone column",
                }
                got = True
                break
            rev, note = try_pdf(p, qe, stored)
            if rev is None:
                # not a terminal refusal while another window remains -- record and keep going
                skips[key] = f"text-layer but {note} ({wname}, {os.path.basename(p)})"
                continue
            out.setdefault(sym, {})[str(qe)] = {
                "rev": rev,
                "op": None,
                "pat_seen": stored,
                "basis": "std",
                "fin": 0,
                "src": f"bse-announcement {att} [{wname}] ({sub[:60]}); {note}",
            }
            skips.pop(key, None)
            print("%-12s %d std -> rev %.2f  [%s | %s]" % (sym, qe, rev, wname, note), flush=True)
            got = True
            break
        if not got:
            skips[key] = "no attachment fetched (all bases + resolver)"
        _flush()
    print(
        "DONE: %d cells read, %d queued for vision, %d skipped"
        % (sum(len(v) for v in out.values()), len(vq), len(skips)),
        flush=True,
    )


if __name__ == "__main__":
    main()
