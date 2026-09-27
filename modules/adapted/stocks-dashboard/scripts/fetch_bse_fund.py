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
"""Extract quarterly Revenue + PAT for the BSE-ONLY universe → docs/bse_fundamentals.json.

⚠️ The BSE `FinancialResult` API is ENTITY-POISONED for many scrips (returns BSE Ltd's numbers, not
the company's — the FORCEMOT contamination pattern; proven again on Cella Space 532701). So we DO NOT
use it. Instead, per scrip, we read the company's OWN result announcement attachment:

  AnnSubCategoryGetData (strCat=-1, per scrip) → pick result/board-outcome filings WITH an attachment
  → AttachLive/AttachHis/<guid>.pdf → OCR pages → IDENTITY-GUARD (company name/ticker must appear)
  → parse the P&L rows (Revenue from Operations, Total Income, Profit for the period) with unit scaling.

Small BSE companies file SCANNED PDFs (no text layer) → OCR (rapidocr) is required. Slow (~10-15s/page),
so this is a resumable background grind: biggest-mcap-first, a per-run budget, progress cached so reruns
skip done scrips. NEVER emit an unanchored value — identity must match and PAT magnitude must be sane.

Store: {"updated", "px":{ "<scripcode>": { "<QE YYYYMMDD>": {"rev":cr,"pat":cr,"ann":YYYYMMDD,"basis":"S|C"} } }}

Run: python -X utf8 scripts/fetch_bse_fund.py [--budget N] [--scrips 532701,...] [--min-mcap CR] [--months M]
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import datetime
import io
import json
import os
import re
import sys
import time

import bse_headers as BH  # §181 BSE headers

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B
import fitz
import qe_util as QU
from rapidocr_onnxruntime import RapidOCR

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "bse_fundamentals.json")
UNIV = os.path.join(HERE, "..", "docs", "bse_universe.json")
DONE = os.path.join(HERE, "_bse_fund_done.json")
FAILS = os.path.join(HERE, "_bse_fund_fail.json")
# code -> YYYYMMDD of the newest declared result filing already handled (read, or given up on). A DONE
# scrip is re-opened when BSE shows a result filing NEWER than this — that is how each new quarter's
# results get read. Without it DONE only grew, and every scrip was skipped for good after one season.
SEEN = os.path.join(HERE, "_bse_fund_seen.json")
MAX_FAIL = 3  # retry a declared-but-unparsed scrip this many runs before giving up
OCR = RapidOCR()
MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
DAY_LAST = {3: 31, 6: 30, 9: 30, 12: 31}
RESULT_HEAD = re.compile(r"result|outcome of (the )?board|financial", re.IGNORECASE)
REV_RE = re.compile(r"revenue from oper", re.IGNORECASE)
INC_RE = re.compile(r"total income", re.IGNORECASE)
PAT_RE = re.compile(r"profit(/loss)? for the (period|year)|profit after tax|net profit", re.IGNORECASE)
BAD_PAT = re.compile(r"before tax|comprehensive|exceptional|other comprehensive", re.IGNORECASE)


def num(s):
    s = s.strip().replace(" ", "")
    if not re.fullmatch(r"\(?-?[\d,]+(?:\.\d+)?\)?", s):
        return None
    v = float(s.strip("()").replace(",", ""))
    return -v if s.startswith("(") else v


def qe_from_text(blob):
    """The quarter a results page states (qe_util.stated_quarter), else the original two patterns."""
    q = QU.stated_quarter(blob)
    if q:
        return q
    m = re.search(
        r"quarter (and year )?ended\s*(on\s*)?(\d{1,2})[\s.\-/]*([A-Za-z]{3,9})[,\s.\-/]*(\d{4})", blob, re.IGNORECASE
    )
    if m:
        mo = MON.get(m.group(4).lower()[:3], 0)
        if mo in DAY_LAST:
            return int(m.group(5)) * 10000 + mo * 100 + DAY_LAST[mo]
    m = re.search(r"ended\s*(on\s*)?([A-Za-z]{3,9})\s*(\d{1,2}),?\s*(\d{4})", blob, re.IGNORECASE)
    if m:
        mo = MON.get(m.group(2).lower()[:3], 0)
        if mo in DAY_LAST:
            return int(m.group(4)) * 10000 + mo * 100 + DAY_LAST[mo]
    return 0


def ocr_boxes(png):
    res, _ = OCR(png)
    return [{"t": t, "x": sum(p[0] for p in b) / 4, "y": sum(p[1] for p in b) / 4} for b, t, sc in (res or [])]


def page_boxes(page):
    """OCR boxes for a page. (A PDF text-layer fast-path was tried but its column geometry differs from
    OCR's and mis-picked P&L cells — e.g. UNIABEXAL PAT 299.3 vs the correct −0.38 — so we OCR uniformly
    for accuracy. Speed instead comes from capping filings/pages and a per-scrip deadline.)"""
    return ocr_boxes(page.get_pixmap(dpi=185).tobytes("png"))


def row_first_num(boxes, label_box):
    """First numeric value to the right of a label box, on the same row."""
    row = [b for b in boxes if abs(b["y"] - label_box["y"]) < 12 and b["x"] > label_box["x"] + 5]
    for b in sorted(row, key=lambda b: b["x"]):
        n = num(b["t"])
        if n is not None:
            return n
    return None


def parse_pl(boxes):
    """Return (rev, pat, unit) from a P&L page's OCR boxes. unit scales to ₹ crore."""
    unit = (
        0.01
        if any(re.search(r"in lakh", b["t"], re.IGNORECASE) for b in boxes)
        else (
            0.1
            if any(re.search(r"in million", b["t"], re.IGNORECASE) for b in boxes)
            else (1.0 if any(re.search(r"in (crore|cr\.)", b["t"], re.IGNORECASE) for b in boxes) else None)
        )
    )
    rev = pat = None
    for b in boxes:
        if rev is None and REV_RE.search(b["t"]):
            rev = row_first_num(boxes, b)
    if rev is None:
        for b in boxes:
            if INC_RE.search(b["t"]):
                rev = row_first_num(boxes, b)
                break
    for b in boxes:
        if pat is None and PAT_RE.search(b["t"]) and not BAD_PAT.search(b["t"]):
            pat = row_first_num(boxes, b)
    return rev, pat, unit


def declared_recently(op, univ_codes, days=110):
    """BSE-only scrips that filed a result (strCat=Result) in the last `days` — grind these FIRST,
    at any market cap, so already-declared results get numbers before the long mcap tail.
    Returns {code: newest filing date YYYYMMDD int} (0 when BSE gave no date)."""
    today = datetime.date.today()
    lo = today - datetime.timedelta(days=days)
    got = {}
    cur = lo
    while cur <= today:
        hi = min(cur + datetime.timedelta(days=9), today)
        F, T = cur.strftime("%Y%m%d"), hi.strftime("%Y%m%d")
        page = 1
        while page <= 40:
            url = (
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=Result"
                "&strPrevDate=%s&strToDate=%s&strScrip=&strSearch=P&strType=C&subcategory=-1" % (page, F, T)
            )
            try:
                tab = json.loads(B.get(op, url)).get("Table", []) or []
            except Exception:
                break
            if not tab:
                break
            for r in tab:
                sc = str(r.get("SCRIP_CD") or "")
                if sc in univ_codes:
                    try:
                        nd = int(str(r.get("NEWS_DT") or "")[:10].replace("-", ""))
                    except ValueError:
                        nd = 0
                    got[sc] = max(got.get(sc, 0), nd)
            page += 1
            time.sleep(0.15)
        cur = hi + datetime.timedelta(days=1)
    return got


def scrip_announcements(op, code, months):
    """Result-filing candidates, newest first: [(YYYY-MM-DD, attachment, 'HEADLINE | NEWSSUB')]. Shared with
    the vision routine (bse_render.announcements): matches HEADLINE + NEWSSUB (runbook §17 — a headline of
    'Please refer the attachment' hid real filings) and drops CFO/newspaper/AGM notices."""
    import bse_render

    return bse_render.announcements(op, code, months)


def fetch_pdf(op, att):
    for base in (
        "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
    ):
        try:
            raw = B.get(op, base + att, b=True)
            if raw[:4] == b"%PDF":
                return raw
        except Exception:
            pass
    return None


def extract(op, code, name, months, deadline=None, have=()):
    """Return {QE: {rev,pat,ann,basis}} for a scrip from its own filings, identity-guarded.
    `deadline` (epoch secs) caps per-scrip work so one heavy filer can't starve a bounded run.
    `have` = quarter keys already stored with a PAT (the vision fallback never re-reads those)."""
    toks = [w for w in re.split(r"[^A-Za-z]+", name.upper()) if len(w) >= 4][:2]
    res = {}
    cands = scrip_announcements(op, code, months)[:3]
    raws = {}  # att -> PDF bytes, reused by the vision fallback
    for annd, att, hd in cands:
        if deadline and time.time() > deadline:
            break
        raw = fetch_pdf(op, att)
        if not raw:
            continue
        raws[att] = raw
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            continue
        qe = 0
        rev = pat = None
        unit = None
        ident = False
        for pi in range(min(len(doc), 6)):
            if deadline and time.time() > deadline:
                break
            boxes = page_boxes(doc[pi])  # text layer if present, else OCR
            blob = " ".join(b["t"] for b in boxes)
            up = blob.upper()
            if not ident and (any(tk in up for tk in toks) if toks else True):
                ident = True
            if not qe:
                qe = qe_from_text(blob)
            if rev is None or pat is None:
                r2, p2, u2 = parse_pl(boxes)
                rev = rev if rev is not None else r2
                pat = pat if pat is not None else p2
                unit = unit or u2
            if ident and qe and pat is not None:
                break
        if ident and qe and unit and pat is not None:
            anni = int(annd.replace("-", "")) if annd else 0
            rec = {"pat": round(pat * unit, 2), "ann": anni, "basis": "C" if "consol" in hd.lower() else "S"}
            if rev is not None:
                rec["rev"] = round(rev * unit, 2)
            # keep the most recent filing per quarter-end
            if qe not in res or anni >= res[qe].get("ann", 0):
                res[qe] = rec
    # VISION FALLBACK: the newest filing's quarter is still missing (a scanned PDF OCR can't anchor) →
    # render its P&L pages and ask a vision reader. CI has no Claude, so this is what fills scanned filings
    # unattended. Readers, in order: bse_vision_api (Anthropic; no-op without ANTHROPIC_API_KEY — unset as
    # of 2026-09-27) then gemini_vision.read_corp_results (Google AI Studio free tier, the key we hold).
    # It runs whenever that quarter is missing — not only when OCR found nothing: an older text-layer filing
    # parsing fine must not hide a scanned new one (it did until 2026-09-27).
    tq = want_quarter(cands, raws)
    LAST_TARGET[code] = tq  # main() judges success against THIS quarter
    if tq and tq not in res and str(tq) not in have and (deadline is None or time.time() < deadline):
        try:
            pngs, ann_i = _render_pl_pngs(op, cands, raws, tq)
        except Exception as ex:
            print("    vision render err:", str(ex)[:70])
            pngs, ann_i = [], 0
        if pngs:
            _vision_fill(res, name, pngs, tq, ann_i)
    return res


LAST_TARGET = {}  # code -> the quarter extract() read the newest filing as (want_quarter), for main()'s success test


def want_quarter(cands, raws=None):
    """The quarter the newest result filing reports: the period its own text states (a late filer's June
    results filed in October say June), else — scanned, no text layer — the last quarter end before its
    filing date."""
    if not cands:
        return 0
    annd, att, _hd = cands[0]
    guess = QU.last_qe_before(annd)
    raw = (raws or {}).get(att)
    if raw:
        import bse_vision_prep as VP

        real = VP.pdf_period(raw)
        if QU.is_qe(real) and real <= guess:
            return real  # never a period ending on/after the filing date
    return guess


def _vision_fill(res, name, pngs, tq, ann_i):
    """Fill res[tq] (and its year-ago quarter) from the rendered P&L pages. Values must come back labelled
    with the quarter they belong to — a column is never re-dated to fit the one we asked for."""
    ya = QU.yago(tq)
    try:
        import bse_vision_api

        v = bse_vision_api.vision_extract_periods(name, pngs)  # reads EVERY printed column with its date
        f = bse_vision_api.TO_CRORE.get((v or {}).get("unit"))
        if v and v.get("ok") and f is not None:
            basis = v.get("basis", "S")
            for p in v.get("periods") or []:
                try:
                    end = int(str(p.get("end") or "").replace("-", ""))
                except ValueError:
                    continue
                if p.get("kind") != "Q" or end not in (tq, ya) or end in res:
                    continue
                if p.get("pat") is None and p.get("rev") is None:
                    continue
                rec = {
                    "pat": (round(float(p["pat"]) * f, 2) if p.get("pat") is not None else None),
                    "ann": (ann_i if end == tq else 0),
                    "basis": basis,
                    "src": "vision",
                }
                if p.get("rev") is not None:
                    rec["rev"] = round(float(p["rev"]) * f, 2)
                res[end] = rec
    except Exception as ex:
        print("    vision fallback err:", str(ex)[:70])
    # FREE reader, second chance. read_corp_results is PAT-only (no revenue in its schema), so cells
    # it fills carry rev=None — the same PAT-only shape the Claude backfills leave behind.
    if not res:
        try:
            import gemini_vision

            if not gemini_vision.quota_dead():
                g = gemini_vision.read_corp_results(name, QU.label(tq), QU.label(QU.prevq(tq)), QU.label(ya), pngs)
                if g and g.get("ok") and g.get("company_matches"):
                    for qe, key in ((tq, "cur"), (ya, "yago")):
                        d = g.get(key) or {}
                        std, con = d.get("std"), d.get("con")
                        # read_corp_results copies a single statement into BOTH slots, so con == std means
                        # standalone-only; only a con that differs from std (or has no std) is consolidated.
                        # (Until 2026-09-27 every Gemini cell was labelled C — BYLD's standalone-only filing.)
                        if con is not None and con != std:
                            pat, basis = con, "C"
                        else:
                            pat, basis = (std if std is not None else con), "S"
                        if pat is None:
                            continue
                        res[qe] = {
                            "pat": round(float(pat), 2),
                            "src": "gemini",
                            "ann": (ann_i if qe == tq else 0),
                            "basis": basis,
                        }
        except Exception as ex:
            print("    gemini fallback err:", str(ex)[:70])


def _render_pl_pngs(op, cands, raws, tq):
    """PNG pages of the first candidate filing (newest first) that could be the tq results filing, via the
    vision routine's own renderer (numeric-density page pick, runbook §17c). TRIPWIRE, same as
    bse_vision_prep: a filing whose text states another quarter is the WRONG announcement — skip it.
    Returns (pngs, announcement date int)."""
    import bse_vision_prep as VP

    for annd, att, _hd in cands:
        raw = raws.get(att) or fetch_pdf(op, att)
        if not raw:
            continue
        real = VP.pdf_period(raw)  # 0 = scanned / unstated: can't tell, don't block
        if real and real != tq:
            continue
        pngs = VP.render_pdf_pages(raw)
        if pngs:
            return pngs, int(annd.replace("-", ""))
    return [], 0


def main():
    budget = int(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 60
    max_min = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 70.0
    t_start = time.time()
    months = int(sys.argv[sys.argv.index("--months") + 1]) if "--months" in sys.argv else 5
    min_mcap = float(sys.argv[sys.argv.index("--min-mcap") + 1]) if "--min-mcap" in sys.argv else 100.0
    only = None
    if "--scrips" in sys.argv:
        only = set(sys.argv[sys.argv.index("--scrips") + 1].split(","))

    univ = json.load(open(UNIV, encoding="utf-8"))["rows"]
    univ.sort(key=lambda r: r[6], reverse=True)  # biggest mcap first
    data = json.loads(open(OUT, encoding="utf-8").read()) if os.path.exists(OUT) else {"px": {}}
    done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
    fails = json.load(open(FAILS)) if os.path.exists(FAILS) else {}  # code -> retry count (declared misses)
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else None  # code -> newest filing date handled

    op = B.session()
    time.sleep(1)

    # DECLARED-FIRST: scrips that filed a result recently are ground first at ANY market cap, so
    # already-declared results (incl. sub-₹100cr names the mcap floor would skip) get numbers first.
    declared = {}
    if only is None and "--no-declared-first" not in sys.argv:
        declared = declared_recently(op, {str(r[0]) for r in univ})
        print("declared recently (BSE-only):", len(declared))
    # NEW-QUARTER RE-OPEN. First run with no SEEN ledger: every DONE scrip's current filing counts as
    # handled (what DONE meant until now), so the ledger starts without a re-read wave. After that, a DONE
    # scrip whose newest result filing is newer than both SEEN and every stored quarter's ann gets ground again.
    save_seen = seen is not None or bool(declared)  # a --scrips run has no declared list: never seed from it
    if seen is None:
        seen = {c: d for c, d in declared.items() if c in done}
        if save_seen:
            print("seen ledger seeded: %d scrips" % len(seen))
    reopened = 0
    for c, d in declared.items():
        if c not in done or not d or d <= int(seen.get(c, 0) or 0):
            continue
        stored = data["px"].get(c, {})
        if d <= max([int(v.get("ann") or 0) for v in stored.values()] or [0]):
            continue
        done.discard(c)
        fails.pop(c, None)
        reopened += 1
    print("re-opened for a newer result filing:", reopened)

    def prio(r):
        return (0 if str(r[0]) in declared else 1, -r[6])  # declared first, then mcap desc

    univ.sort(key=prio)

    spent = 0
    for r in univ:
        code, tkr, name, _isin, _grp, _fv, mc, _sec = r
        code = str(code)
        if only is not None:
            if code not in only and tkr not in only:
                continue
        else:
            # skip done; apply the mcap floor ONLY to non-declared names (declared always qualify)
            if code in done:
                continue
            if code not in declared and mc < min_mcap:
                continue
        if spent >= budget or (time.time() - t_start) / 60 >= max_min:
            break
        spent += 1
        cur = data["px"].get(code, {})
        have = {q for q, c in cur.items() if c.get("pat") is not None}
        try:
            recs = extract(op, code, name, months, deadline=time.time() + 120, have=have)  # ≤2 min/scrip
        except Exception as ex:
            print(f"  {code} {tkr} ERR {str(ex)[:60]}")
            recs = {}
        added = 0
        recs = {q: r for q, r in recs.items() if QU.is_qe(q)}  # never store a garbled period (26310331)
        for qe, rec in recs.items():  # fill-only: add a quarter, or a figure
            old = cur.get(str(qe))  # a stored cell lacks (same basis only)
            if old is None:
                cur[str(qe)] = rec
                added += 1
            elif old.get("basis", rec.get("basis")) == rec.get("basis"):
                for k in ("pat", "rev"):
                    if old.get(k) is None and rec.get(k) is not None:
                        old[k] = rec[k]
                        added += 1
        if cur:
            data["px"][code] = cur
        # SUCCESS. A declared scrip is handled once its newest filing's quarter is stored with a PAT, or this
        # run added something. Just re-parsing an OLDER filing whose numbers are already stored is not
        # success — it used to mark the scrip done/seen and the new quarter was never read.
        if code in declared:
            # the quarter the newest filing REPORTS (its printed period — a late March result filed in
            # September is March), not the last quarter end before the declared date
            wq = LAST_TARGET.get(code) or (QU.last_qe_before(declared[code]) if declared[code] else 0)
            ok = added > 0 or (wq and (cur.get(str(wq)) or {}).get("pat") is not None)
        else:
            ok = bool(recs)
        if ok:
            latest = max(recs) if recs else None
            print(
                "  ✓ %s %-12s %s PAT=%s rev=%s (+%d)"
                % (code, tkr, latest, (recs.get(latest) or {}).get("pat"), (recs.get(latest) or {}).get("rev"), added)
            )
            done.add(code)
            fails.pop(code, None)
            if declared.get(code):
                seen[code] = declared[code]
        else:
            print("  · %s %-12s (no anchored result%s)" % (code, tkr, " for its newest filing" if recs else ""))
            # Record the failed attempt for EVERY scrip (declared or targeted) — this count drives the
            # page's "filing available — PDF only" label once a filed co has resisted parsing (fail>=2),
            # so users know its number isn't merely queued. A DECLARED scrip keeps retrying up to
            # MAX_FAIL runs (transient/parse miss); a non-declared one is done after this attempt.
            fails[code] = fails.get(code, 0) + 1
            if code not in declared or fails[code] >= MAX_FAIL:
                done.add(code)
                if declared.get(code):
                    seen[code] = declared[code]
        if spent % 10 == 0:
            ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
            data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            json.dump(sorted(done), open(DONE, "w"))
            json.dump(fails, open(FAILS, "w"))
            if save_seen:
                json.dump(seen, open(SEEN, "w"), sort_keys=True)
            time.sleep(0.2)
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(sorted(done), open(DONE, "w"))
    json.dump(fails, open(FAILS, "w"))
    if save_seen:
        json.dump(seen, open(SEEN, "w"), sort_keys=True)
    ncov = len(data["px"])
    print("WROTE %s: processed %d scrips this run; %d scrips now have numbers" % (os.path.normpath(OUT), spent, ncov))


if __name__ == "__main__":
    main()
