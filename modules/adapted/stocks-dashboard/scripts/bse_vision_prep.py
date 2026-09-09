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
"""Prep step for the scheduled vision-fill routine. Finds companies — NSE **and** BSE-only — that FILED a
result for the current quarter but whose numbers we don't have yet, renders each one's P&L pages to PNGs,
and writes a manifest. A Claude routine then READS those PNGs (vision) and fills the numbers via
merge_bse_vision.py. This is the safety net that guarantees no declared result stays "numbers being
parsed" forever — NSE names whose XBRL hasn't posted, and scanned BSE micro-caps OCR can't read, both
get read from their own filing PDF.

No API key needed — the reading is done by the routine's own Claude, on the user's plan.

Output: <outdir>/manifest.json = [{exch:"NSE"|"BSE", sym, scrip, name, mcap, pngs:[abs paths]}], NSE first
then biggest-mcap.

Run: python -X utf8 scripts/bse_vision_prep.py [--limit N] [--outdir DIR]
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

import bse_fetch as B
import bse_render
import fetch_announcements as FA
import fitz
from results_pending import find_pending, find_unknown_qe  # shared with build_results_coverage.py

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "docs")
NSE_PDF = "https://nsearchives.nseindia.com/corporate/"
WORKER = "https://stocksworld-quotes.dhruvan2510.workers.dev"  # ?pdf= relay (live-quote-worker.js)


def norm(s):
    return re.sub(r"(limited|ltd)$", "", re.sub(r"[^a-z0-9]", "", str(s).lower()))


# The results table can sit deep in a filing — banks bury it behind a 8-10 page joint-auditors' report —
# and PL_HINT matches those auditor pages too ("net profit/(loss) after tax"). Scanning only the first 8
# pages and keeping the first 4 hits therefore rendered the review report and never reached the numbers
# (CENTRALBK Q1FY27: consolidated table on page 10 of 31). Scan wider and rank by NUMERIC DENSITY: a real
# results table is wall-to-wall figures (98-196 numeric tokens/page) while prose pages that merely mention
# profit have far fewer (<=32), so the table wins regardless of where in the filing it sits.
#
# A text-less page is a SCANNED image we can't score — it may be the table or may be a scanned review
# report. It must sit BETWEEN the two: above prose (we can't rule it out) but below a confirmed table
# (never crowd out real numbers). TELGE Q1FY27 is the case that pins this down — tables on pages 4 and
# 11, four blank scanned pages around them; ranking blanks first rendered all four blanks and neither
# table. In an all-scanned filing every page ties here and doc order is preserved, as before.
# ⚠️ NUM_TOK must count SMALL decimals too. The old pattern (\d[\d,]{2,}) required 3+ digits, so a
# micro-cap table whose figures are 3.19 / 22.86 / 7.00 scored near-zero while a scanned blank scored 40.
# VIRTUALG Q1FY27 (2026-07-23) is the case: P&L on pages 2 and 6 scored 34 each, SIX blank pages scored
# 40, the 4-page budget went entirely to blanks, and the routine reported "auditor report only, no P&L"
# for a filing that plainly had one. Counting any digit-run — decimals included — puts those tables at
# 100+ and back on top.
NUM_TOK = re.compile(r"\d[\d,.]*\d|\d")
SCAN_SCORE = 40  # a text-less page: can't be scored, must outrank prose but never a real table


def render_pdf_pages(raw):
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        return []
    cands = []
    for pi in range(min(len(doc), 24)):
        txt = doc[pi].get_text()
        if not txt.strip():
            score = SCAN_SCORE  # scanned page — no text to judge, worth a look
        elif bse_render.PL_HINT.search(txt):
            score = len(NUM_TOK.findall(txt))  # P&L-ish prose vs an actual table of numbers
        else:
            continue
        cands.append((-score, pi))
    cands.sort()
    # Keep up to 4 pages, but NEVER let blanks crowd out a scored table: take scored pages first, then
    # fill any remaining slots with blanks. Without this a filing with 2 tables + 6 blanks still loses
    # half its budget to blanks even once the tables outrank them.
    scored = [pi for s, pi in cands if -s != SCAN_SCORE]
    blanks = [pi for s, pi in cands if -s == SCAN_SCORE]
    keep = sorted((scored + blanks)[:4])
    if not keep:
        # ⚠️ EVERY page carried a text layer and NONE matched PL_HINT, so the loop above `continue`d
        # on all of them and this was about to return nothing at all. That is the FILTER hiding the
        # statement, not the filing lacking one — the same family as the page_basis trap (§71k). A
        # SCANNED filing with an OCR text layer never scores SCAN_SCORE (it isn't blank) and its
        # garbled wording defeats PL_HINT, so it falls through both branches. 16 names were dropped
        # this way on 2026-08-18, every one of them with a real P&L inside the PDF. Rank by numeric
        # density alone — a results table is wall-to-wall figures whatever words survived OCR — and
        # if no page is dense either, hand back the opening pages so a reader can still LOOK.
        dens = sorted(
            ((len(NUM_TOK.findall(doc[pi].get_text())), pi) for pi in range(min(len(doc), 30))), key=lambda t: -t[0]
        )
        keep = sorted(pi for n, pi in dens[:4] if n >= 25) or list(range(min(len(doc), 4)))
    return [doc[pi].get_pixmap(dpi=200).tobytes("png") for pi in keep]


def pdf_period(raw):
    """Read the reporting quarter the FILING itself states (not the — sometimes wrong — NSE caption).
    Late Q4/annual filings are frequently mislabelled by NSE as the current quarter; the audit report/
    P&L always says 'quarter ... ended <date>'. Returns a quarter-end int (e.g. 20260331) or 0."""
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        return 0
    txt = " ".join(doc[pi].get_text() for pi in range(min(len(doc), 4)))
    return FA.parse_qe(txt)


MONTHS = [
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
]


def names_quarter(txt, qe):
    """True when TXT explicitly names the quarter-end we are filling.

    Used on a BSE announcement's HEADLINE+NEWSSUB, which is an INDEPENDENT witness to the PDF's own
    text layer — and on scanned or stale-templated filings it is the more reliable of the two.
    HIPOLIN's 2026-08-14 filing has a text layer that parses to 20251231 and SUPERBAK's to 20160630,
    so pdf_period vetoed both; 23 real June filings were refused that way on 2026-08-18, identically
    on every run, with the log saying only "no candidate yielded a P&L". When the announcement names
    the target quarter we render anyway and let the READER confirm the period printed on the page.
    """
    y, m, d = qe // 10000, qe // 100 % 100, qe % 100
    mon = MONTHS[m - 1]
    t = re.sub(r"\s+", " ", str(txt or "").lower())
    pats = [
        r"%02d[./-]%02d[./-]%04d" % (d, m, y),
        r"\b%d[./-]%d[./-]%d\b" % (d, m, y),
        r"%s\s*%d,?\s*%d" % (mon, d, y),
        r"%d(?:st|nd|rd|th)?\s+%s,?\s*%d" % (d, mon, y),
    ]
    return any(re.search(pt, t) for pt in pats)


def pdf_mentions_qe(raw, qe):
    """Does the filing itself print the target quarter-end anywhere in its opening pages?

    pdf_period() joins several pages and returns ONE date, so a statement headed "Quarter ended
    30/06/2026" that also carries "year ended 31/03/2026" columns can parse to the wrong quarter —
    DAULAT|2026-08-14 did exactly that on 2026-08-18 and was about to be re-filed into March. When
    both quarters appear the parse is AMBIGUOUS, and an ambiguous parse must never silently re-file
    a row: render it and let the reader adjudicate off the printed header.
    """
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        return False
    return names_quarter(" ".join(doc[pi].get_text() for pi in range(min(len(doc), 6))), qe)


# ---------------- FIX 1: the qe==0 queue must not be head-of-line blocked ----------------
QEFAIL = os.path.join(HERE, "_qe_unreadable.json")


def qe_attempts():
    try:
        return json.load(open(QEFAIL, encoding="utf-8"))
    except Exception:
        return {}


def pick_unknown(qelimit):
    """The qe==0 rows to probe this run — FRESH ONES FIRST.

    find_unknown_qe() ranks purely by market cap and main() used to call it with NO argument at all,
    taking its default top 12. Names whose period the text layer simply cannot state (scanned cover
    pages) never resolve, never leave the pending list, and — being the largest of the unresolved —
    sit at the head of that ranking FOREVER. Measured 2026-08-18: 4 of the 12 probed slots were
    permanently held by GRANDOAK / GOURMET / PANCM / JOHNPHARMA, leaving 8 usable probes a day
    against a backlog of 79. Sorting by (attempts so far, then mcap) lets a repeatedly unreadable
    name drift to the BACK of the queue without ever being dropped, so every fresh filing is probed
    before any repeat offender, and the stuck ones still come round again.
    """
    rows = find_unknown_qe(10**6)
    att = qe_attempts()
    rows.sort(key=lambda r: (int(att.get(f"{r[0]}|{r[4]}", 0)), -(r[2] or 0)))
    return rows[:qelimit], att


def enrich_scrips(limit):
    """BSE-only companies we already cover but that are MISSING the year-ago quarter (filled by the
    fast OCR pass, which only grabbed the current quarter) — re-render so vision can add YoY/QoQ."""
    bf = json.load(open(os.path.join(D, "bse_fundamentals.json"), encoding="utf-8"))["px"]
    univ = {str(r[0]): r for r in json.load(open(os.path.join(D, "bse_universe.json"), encoding="utf-8"))["rows"]}
    out = []
    for scrip, qs in bf.items():
        if "20260630" in qs and "20250630" not in qs and scrip in univ:  # has current, missing year-ago
            r = univ[scrip]
            out.append((scrip, (r[1].upper(), r[2], r[6])))
    out.sort(key=lambda kv: -(kv[1][2] or 0))
    return out[:limit]


# NSE rate-limits archive downloads per IP: after a burst it answers 403 (or 429). Before 2026-07-19
# the prep just printed "fetch err 403" and `continue`d — so one throttle abandoned that name for the
# whole run, and because the NEXT scheduled run could hit the same wall at the same point, big filers
# (AXISBANK/KOTAKBANK/PNB/INDIACEM/JKCEMENT, 2026-07-18) sat unfilled across BOTH runs. Fix: never skip
# on a retryable error — wait (growing backoff), re-warm the NSE session cookie (a fresh jar clears the
# throttle), and try again. Only a hard 404 / non-retryable status gives up. A 200 that isn't a %PDF
# (NSE error/te stub) is treated as retryable too.
def _nse_warm(NB):
    """Cookie jar warmed on BOTH the home page and the announcements page — nsearchives
    checks that the session has 'visited' the referer page before it serves an attachment."""
    jar = NB.nse_jar()  # home + financial-results
    with contextlib.suppress(Exception):
        NB._get(
            "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            headers={"User-Agent": NB.UA, "Accept": "text/html"},
            jar=jar,
            timeout=20,
        )
    return jar


RETRYABLE = {403, 429, 500, 502, 503, 504}


def _nse_pdf_with_retry(NB, url, hdr, jar_box, sym, tries=3):  # brief ride-out; BSE fallback covers a hard block
    import urllib.error

    delay = 5
    for attempt in range(1, tries + 1):
        reason = None
        try:
            raw = NB._get(url, headers=hdr, jar=jar_box[0], timeout=60, binary=True)
            if raw and raw[:4] == b"%PDF":
                return raw
            reason = "non-PDF (%d bytes)" % (len(raw) if raw else 0)
        except urllib.error.HTTPError as ex:
            reason = f"HTTP {ex.code}"
            if ex.code not in RETRYABLE:
                print("  NSE %-11s hard %s — not retryable" % (sym, reason))
                return None
        except Exception as ex:
            reason = type(ex).__name__
        if attempt < tries:
            print("  NSE %-11s %s — retry %d/%d in %ds (re-warm cookie)" % (sym, reason, attempt, tries - 1, delay))
            time.sleep(delay)
            try:
                jar_box[0] = _nse_warm(NB)  # fresh cookies + pause clears NSE's per-IP throttle
            except Exception:
                pass
            delay = min(delay * 2, 60)
    # Last transport: our Cloudflare Worker's ?pdf= relay. CF's edge still passes NSE's Akamai
    # while every scripted IP we have (GitHub runners, local python, curl_cffi Chrome-TLS) is
    # hard-403'd (2026-07-21) — without this, NSE-only names with no BSE copy stay unfetchable.
    # Harmless before the worker route is deployed: the 400/502 JSON fails the %PDF check.
    try:
        import urllib.request

        fn = url.rstrip("/").rsplit("/", 1)[-1]
        # browser UA required: Cloudflare's OWN bot protection (error 1010) bans bare
        # python-urllib signatures at the workers.dev front door — the worker never sees it
        req = urllib.request.Request(
            WORKER + "/?pdf=" + fn, headers={"User-Agent": NB.UA, "Accept": "application/pdf,*/*"}
        )
        raw = urllib.request.urlopen(req, timeout=60).read()
        if raw[:4] == b"%PDF":
            print("  NSE %-11s fetched via CF worker relay" % sym)
            return raw
        print("  NSE %-11s relay served non-PDF (%d bytes)" % (sym, len(raw) if raw else 0))
    except Exception as ex:
        print("  NSE %-11s relay failed: %s" % (sym, type(ex).__name__))
    return None


def _bse_fallback(sym, by_id, op_box, outdir, qe):
    """When NSE's nsearchives hard-403s a scripted download, a DUAL-LISTED name can be read off
    BSE (AttachLive/AttachHis) instead — BSE doesn't block us, so this is what actually rescues the
    big banks/large-caps (AXISBANK/KOTAK/PNB/INDIACEM/JKCEMENT, 2026-07-18) when the NSE fetch fails.
    Numbers still route to vision_fills as an NSE fill (manifest exch stays 'NSE'); we only borrow the
    BSE PDF. Returns rendered NSE_<sym>_pN.png paths, or [] (NSE-only SME, or BSE has no matching filing).
    Same quarter tripwire as the BSE branch: never render a filing whose stated period isn't the target."""
    scrip = by_id.get(sym)
    if not scrip:
        return []  # NSE-only (e.g. an SME) — no BSE copy exists
    import bse_fetch as B
    import bse_render

    if op_box[0] is None:
        op_box[0] = B.session()
        time.sleep(1)
    op = op_box[0]
    try:
        anns = bse_render.announcements(op, str(scrip))[:4]
    except Exception as ex:
        print("  NSE %-11s BSE-fallback error %s" % (sym, type(ex).__name__))
        return []
    for _annd, att, _hd in anns:
        raw = bse_render.fetch_pdf(op, att)
        if not raw:
            continue
        real = pdf_period(raw)
        if real and real != qe:  # wrong quarter's filing — try the next candidate
            continue
        pngs = []
        for i, png in enumerate(render_pdf_pages(raw)):
            p = os.path.join(outdir, "NSE_%s_p%d.png" % (sym, i))
            open(p, "wb").write(png)
            pngs.append(p)
        if pngs:
            return pngs
    return []


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 25
    outdir = (
        sys.argv[sys.argv.index("--outdir") + 1]
        if "--outdir" in sys.argv
        else os.path.join(os.environ.get("TEMP", "/tmp"), "bse_pending")
    )
    os.makedirs(outdir, exist_ok=True)
    if "--enrich" in sys.argv:  # re-render already-covered names missing year-ago
        qe, nse, bse = 20260630, [], enrich_scrips(limit)
    else:
        qe, nse, bse = find_pending(limit)
    print("target quarter %d — pending: %d NSE, %d BSE-only" % (qe, len(nse), len(bse)))
    manifest = []

    # ---- NSE (fetch each announcement PDF from nsearchives) ----
    qfix = {}  # "SYM|YYYY-MM-DD" -> real quarter-end, when NSE's caption quarter is wrong
    if nse:
        import build_fundamentals as NB

        try:
            by_id = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
        except Exception:
            by_id = {}  # SYM -> BSE scrip, for the dual-listed fallback
        bse_op_box = [None]  # lazy BSE session, only opened if an NSE fetch fails
        # nsearchives 403s scripted downloads unless the request looks like a real browser click
        # from the announcements page (Referer + Sec-Fetch + a session cookie warmed on that page).
        hdr = {
            "User-Agent": NB.UA,
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            "Accept": "application/pdf,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        jar_box = [_nse_warm(NB)]  # mutable holder so a retry can swap in a fresh cookie jar
        for sym, name, mcap, fn, fdate in nse:
            if not fn:
                print("  ✗ NSE %-11s no attachment on the feed row — nothing to fetch" % sym)
                continue
            # ⚠️ ROUTE BY HOST, NOT BY FEED SIDE. An NSE-side feed row routinely carries a BSE-hosted
            # attachment URL (…bseindia.com/xml-data/corpfiling/AttachLive/<guid>.pdf). Sending that
            # to _nse_pdf_with_retry with NSE cookies and an nsearchives Referer fetches the 1-page
            # COVER LETTER to BSE (or junk); render_pdf_pages then returned [] and the loop fell out
            # of the bottom with NO log line at all. 12 names were abandoned invisibly on every run
            # (2026-08-18: ABAN, AJEL, AJIL, ANSALAPI, ARSHIYA, ASIANFR, MAHANIN, MYSPAPE, NAGAFERT,
            # NDMETAL, PARSVNATH, NIWASSP) — the run log never even named them.
            if "bseindia.com" in str(fn):
                if bse_op_box[0] is None:
                    bse_op_box[0] = B.session()
                    time.sleep(1)
                raw = bse_render.fetch_pdf(bse_op_box[0], str(fn).rstrip("/").rsplit("/", 1)[-1])
                if not raw:
                    print("  NSE %-11s BSE-hosted attachment did not fetch" % sym)
            else:
                url = fn if str(fn).startswith("http") else NSE_PDF + fn
                raw = _nse_pdf_with_retry(NB, url, hdr, jar_box, sym)
            if not raw:
                # NSE blocked the download — read the SAME result off BSE (dual-listed names)
                fb = _bse_fallback(sym, by_id, bse_op_box, outdir, qe)
                if fb:
                    manifest.append({"exch": "NSE", "sym": sym, "scrip": "", "name": name, "mcap": mcap, "pngs": fb})
                    print("  rendered NSE %-11s via BSE fallback (%d pages)" % (sym, len(fb)))
                else:
                    print("  NSE %-11s UNFETCHED (NSE 403 + no BSE copy) — left pending" % sym)
                continue
            real = pdf_period(raw)  # what the filing itself says
            if real and str(fdate)[:10] <= "%04d-%02d-%02d" % (real // 10000, real // 100 % 100, real % 100):
                # impossible: the "period" ends on/after the filing date — the parse grabbed some other
                # date in the PDF (validity/meeting/record date). Never ledger an impossible quarter.
                print("  qfix NSE %-11s filing=%d IMPOSSIBLE vs filed %s — ignored" % (sym, real, fdate))
                real = 0
            if real and real != qe:  # NSE caption mislabelled the quarter
                qfix[f"{sym}|{fdate}"] = real
                print("  qfix NSE %-11s caption=%d -> filing=%d (skip)" % (sym, qe, real))
                continue
            pngs = []
            for i, png in enumerate(render_pdf_pages(raw)):
                p = os.path.join(outdir, "NSE_%s_p%d.png" % (sym, i))
                open(p, "wb").write(png)
                pngs.append(p)
            if pngs:
                manifest.append({"exch": "NSE", "sym": sym, "scrip": "", "name": name, "mcap": mcap, "pngs": pngs})
                print("  rendered NSE %-11s (%d pages)" % (sym, len(pngs)))
            else:
                # The attachment fetched but yielded no page — almost always a cover letter, with the
                # statement filed as a SEPARATE announcement. Ask BSE for the sibling filings before
                # giving up, and if that fails too, SAY SO. This branch is where the 12 names vanished.
                fb = _bse_fallback(sym, by_id, bse_op_box, outdir, qe)
                if fb:
                    manifest.append({"exch": "NSE", "sym": sym, "scrip": "", "name": name, "mcap": mcap, "pngs": fb})
                    print("  rendered NSE %-11s via BSE sibling announcement (%d pages)" % (sym, len(fb)))
                else:
                    print(
                        "  ✗ NSE %-11s: attachment carried no P&L page and no BSE sibling filing did "
                        "either — NOT proof it didn't file; check the announcement pick" % sym
                    )
            time.sleep(1.5)  # space downloads out so we don't trip NSE's per-IP rate limit
    # ---- qe==0 feed rows (period unstated in the filing text): resolve the REAL quarter from the
    # filing PDF itself, and — when it turns out to be the target quarter — render it right away so
    # the numbers fill in THIS run. Before 2026-07-21 these rows were invisible to every counter and
    # to this routine (YESBANK filed Sat 2026-07-18 13:41, sat unclassified for 3 days).
    qelimit = int(sys.argv[sys.argv.index("--qelimit") + 1]) if "--qelimit" in sys.argv else 40
    unknown, qeatt = pick_unknown(qelimit)
    if unknown:
        import build_fundamentals as NBu

        try:
            by_idu = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
        except Exception:
            by_idu = {}
        hdru = {
            "User-Agent": NBu.UA,
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            "Accept": "application/pdf,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        jaru, opu = [None], [None]
        for sym, name, mcap, fn, fdate, scrip in unknown:
            raw = None
            if fn and "bseindia.com" in str(fn):  # BSE-sourced feed row
                if opu[0] is None:
                    opu[0] = B.session()
                    time.sleep(1)
                raw = bse_render.fetch_pdf(opu[0], str(fn).rstrip("/").rsplit("/", 1)[-1])
            elif fn:  # NSE-sourced feed row
                if jaru[0] is None:
                    jaru[0] = _nse_warm(NBu)
                url = fn if str(fn).startswith("http") else NSE_PDF + fn
                raw = _nse_pdf_with_retry(NBu, url, hdru, jaru, sym)
            if not raw:  # last resort: BSE copy, SAME day only
                sc = str(scrip or by_idu.get(sym) or "")
                if sc:
                    if opu[0] is None:
                        opu[0] = B.session()
                        time.sleep(1)
                    for annd, att, _hd in bse_render.announcements(opu[0], sc)[:4]:
                        if annd != fdate:
                            continue  # a different day = a different filing
                        raw = bse_render.fetch_pdf(opu[0], att)
                        if raw:
                            break
            real = pdf_period(raw) if raw else 0
            if real and str(fdate)[:10] <= "%04d-%02d-%02d" % (real // 10000, real // 100 % 100, real % 100):
                print(
                    "  qe? %-11s %s -> %d IMPOSSIBLE (period ends on/after filing date) — left unclassified"
                    % (sym, fdate, real)
                )
                real = 0
            if not real:
                print("  qe? %-11s %s — period unreadable (scanned/blocked), left unclassified" % (sym, fdate))
                qeatt[f"{sym}|{fdate}"] = int(qeatt.get(f"{sym}|{fdate}", 0)) + 1
                continue
            # AMBIGUOUS: pdf_period joins several pages and returns ONE date, so a statement headed
            # "Quarter ended 30/06/2026" that also carries year-ended-31/03/2026 columns can parse to
            # the wrong quarter. DAULAT|2026-08-14 did exactly that (2026-08-18) and was one merge away
            # from being re-filed into March. A ledgered quarter fix is not a guess we get to make on a
            # coin toss — when the filing prints the target quarter TOO, write nothing and render it.
            ambiguous = bool(real != qe and pdf_mentions_qe(raw, qe))
            if ambiguous:
                print(
                    "  qe? %-11s %s -> parsed %d BUT the filing also prints %d — ambiguous, no quarter "
                    "fix ledgered; rendering for the reader to adjudicate" % (sym, fdate, real, qe)
                )
            else:
                qfix[f"{sym}|{fdate}"] = real
                print(
                    "  qe? %-11s %s -> %d%s"
                    % (sym, fdate, real, " (target quarter — rendering now)" if real == qe else "")
                )
            qeatt.pop(f"{sym}|{fdate}", None)  # resolved — clear any earlier failed attempts
            if real == qe or ambiguous:
                pngs = []
                for i, png in enumerate(render_pdf_pages(raw)):
                    p = os.path.join(outdir, "%s_%s_p%d.png" % ("BSE" if scrip else "NSE", scrip or sym, i))
                    open(p, "wb").write(png)
                    pngs.append(p)
                if pngs:
                    manifest.append(
                        {
                            "exch": "BSE" if scrip else "NSE",
                            "sym": sym,
                            "scrip": scrip,
                            "name": name,
                            "mcap": mcap,
                            "pngs": pngs,
                        }
                    )

    # merge quarter corrections into the persistent side-file (write_results_feed applies them hourly)
    fixp = os.path.join(D, "feed_qe_fix.json")
    try:
        allfix = json.load(open(fixp, encoding="utf-8"))
    except Exception:
        allfix = {}
    allfix.update(qfix)
    if qfix:
        json.dump(allfix, open(fixp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("WROTE %s: +%d quarter fixes (%d total)" % (os.path.normpath(fixp), len(qfix), len(allfix)))
    # ⚠️ That repo edit does NOT survive the scheduled routine. The laptop can sleep for hours mid-run, so
    # SKILL step 5 re-syncs (`git reset --hard origin/main`) before merging — which throws this working-tree
    # write away. Re-running prep cannot regenerate it either: the names it resolved are no longer pending,
    # so they're never re-scanned. 2026-07-27 lost 4 fixes that way (59 -> 55 entries), including
    # HMT|2026-07-27 and SGLRES|2026-07-27 -> 20260331, which would have left both phantom-pending on the
    # wrong quarter. So journal this run's fixes OUTSIDE the repo, beside the manifest, and let
    # `merge_bse_vision.py --qefix <this file>` re-apply them AFTER the re-sync. Written even when empty,
    # so "nothing to fix" is distinguishable from "the routine forgot to pass --qefix".
    runp = os.path.join(outdir, "qe_fix_run.json")
    json.dump(qfix, open(runp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "WROTE %s: %d quarter fixes for `merge_bse_vision.py --qefix` to re-apply after the re-sync"
        % (os.path.normpath(runp), len(qfix))
    )

    # ---- BSE-only (via bse_fetch) ----
    if bse:
        op = B.session()
        time.sleep(1)
        for scrip, (tkr, name, mcap) in bse:
            pngs = []
            # try the next-best announcement when one yields no P&L pages (a board-outcome cover letter
            # often has none) — costs extra BSE hits only on the names that would otherwise stay empty
            for annd, att, _hd in bse_render.announcements(op, scrip)[:3]:
                raw = bse_render.fetch_pdf(op, att)
                if not raw:
                    continue
                # TRIPWIRE: never hand vision a PDF for the wrong quarter. If the filing states a period and
                # it isn't the one we're filling, we picked the WRONG ANNOUNCEMENT — that is a fetch bug on
                # our side, NOT evidence the company skipped the quarter. Rendering it anyway is how
                # GYANDEV/NAM (2026-07-17) got read off their March PDF and reported as "never filed June",
                # for names that had filed that morning. Skip to the next candidate and say so out loud.
                # period 0 = scanned/no text layer: we genuinely can't tell, so don't block on it.
                real = pdf_period(raw)
                if real and real != qe:
                    print(
                        "  ⚠ BSE %-11s %s: filing states %d, want %d — wrong announcement, trying next"
                        % (tkr, annd, real, qe)
                    )
                    continue
                for i, png in enumerate(render_pdf_pages(raw)):
                    p = os.path.join(outdir, "BSE_%s_p%d.png" % (scrip, i))
                    open(p, "wb").write(png)
                    pngs.append(p)
                if pngs:
                    break
            if pngs:
                manifest.append({"exch": "BSE", "sym": tkr, "scrip": scrip, "name": name, "mcap": mcap, "pngs": pngs})
                print("  rendered BSE %s %-11s (%d pages)" % (scrip, tkr, len(pngs)))
            else:
                print(
                    "  ✗ BSE %s %-11s: no candidate yielded a %d P&L — NOT proof it didn't file; check "
                    "the announcement pick (runbook 17) before concluding anything" % (scrip, tkr, qe)
                )

    # Persist the qe-probe attempt counts so the NEXT run starts with names it has never tried.
    # Without this the ranking is pure mcap and the same unreadable filings hold the head of the
    # queue on every run — the head-of-line block that left 8 usable probes a day against 79 waiting.
    try:
        json.dump(qeatt, open(QEFAIL, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        stuck = sum(1 for v in qeatt.values() if int(v) >= 3)
        print(
            "WROTE %s: %d names with an unread period (%d tried 3+ times — they now sort LAST, "
            "never dropped)" % (os.path.normpath(QEFAIL), len(qeatt), stuck)
        )
    except Exception as ex:
        print(f"  ⚠ could not write {QEFAIL} ({ex}) — next run reverts to mcap-only order")

    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"))
    print("WROTE %s/manifest.json: %d companies ready to vision-read" % (outdir, len(manifest)))


if __name__ == "__main__":
    main()
