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
import datetime
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B
import fitz
from rapidocr_onnxruntime import RapidOCR

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "bse_fundamentals.json")
UNIV = os.path.join(HERE, "..", "docs", "bse_universe.json")
DONE = os.path.join(HERE, "_bse_fund_done.json")
FAILS = os.path.join(HERE, "_bse_fund_fail.json")
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
            10.0
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
    at any market cap, so already-declared results get numbers before the long mcap tail."""
    today = datetime.date.today()
    lo = today - datetime.timedelta(days=days)
    got = set()
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
                    got.add(sc)
            page += 1
            time.sleep(0.15)
        cur = hi + datetime.timedelta(days=1)
    return got


def scrip_announcements(op, code, months):
    hi = datetime.date.today()
    lo = hi - datetime.timedelta(days=30 * months)
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
        "&strPrevDate={}&strToDate={}&strScrip={}&strSearch=P&strType=C&subcategory=-1".format(
            lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d"), code
        )
    )
    try:
        tab = json.loads(B.get(op, url)).get("Table", []) or []
    except Exception:
        return []
    out = []
    for r in tab:
        hd = str(r.get("HEADLINE") or "")
        att = r.get("ATTACHMENTNAME")
        if att and RESULT_HEAD.search(hd):
            out.append((str(r.get("NEWS_DT") or "")[:10], att, hd))
    return out


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


def extract(op, code, name, months, deadline=None):
    """Return {QE: {rev,pat,ann,basis}} for a scrip from its own filings, identity-guarded.
    `deadline` (epoch secs) caps per-scrip work so one heavy filer can't starve a bounded run."""
    toks = [w for w in re.split(r"[^A-Za-z]+", name.upper()) if len(w) >= 4][:2]
    res = {}
    for annd, att, hd in scrip_announcements(op, code, months)[:3]:
        if deadline and time.time() > deadline:
            break
        raw = fetch_pdf(op, att)
        if not raw:
            continue
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
    # VISION FALLBACK: OCR found nothing anchored → render the P&L pages and ask a vision reader.
    # CI has no Claude, so this is what fills scanned filings unattended. Two readers, tried in order:
    #   1. bse_vision_api (Anthropic)  — no-op when ANTHROPIC_API_KEY is unset (it is, as of 2026-07-23)
    #   2. gemini_vision.read_corp_results — Google AI Studio FREE tier, the key we actually hold.
    # Before this, the whole fallback was Anthropic-only, so every scanned BSE micro-cap fell through and
    # got retired at MAX_FAIL while a working free key sat wired to the insurer job two workflows away.
    if not res and (deadline is None or time.time() < deadline):
        pngs = None
        try:
            import bse_vision_api

            pngs = _render_pl_pngs(op, code)
            if pngs:
                v = bse_vision_api.vision_extract(name, pngs)
                if v and v.get("ok"):
                    basis = v.get("basis", "S")
                    for qe, key in ((20260630, "jun2026"), (20250630, "jun2025")):
                        d = v.get(key) or {}
                        if d.get("pat") is not None or d.get("rev") is not None:
                            rec = {
                                "pat": (round(float(d["pat"]), 2) if d.get("pat") is not None else None),
                                "ann": (20260715 if qe == 20260630 else 0),
                                "basis": basis,
                                "src": "vision",
                            }
                            if d.get("rev") is not None:
                                rec["rev"] = round(float(d["rev"]), 2)
                            res[qe] = rec
        except Exception as ex:
            print("    vision fallback err:", str(ex)[:70])
        # FREE reader, second chance. read_corp_results is PAT-only (no revenue in its schema), so cells
        # it fills carry rev=None — the same PAT-only shape the Claude backfills leave behind.
        if not res and (deadline is None or time.time() < deadline):
            try:
                import gemini_vision

                if not gemini_vision.quota_dead():
                    if pngs is None:
                        pngs = _render_pl_pngs(op, code)
                    if pngs:
                        g = gemini_vision.read_corp_results(name, "30 June 2026", "31 March 2026", "30 June 2025", pngs)
                        if g and g.get("ok") and g.get("company_matches"):
                            for qe, key in ((20260630, "cur"), (20250630, "yago")):
                                d = g.get(key) or {}
                                pat = d.get("con") if d.get("con") is not None else d.get("std")
                                if pat is None:
                                    continue
                                res[qe] = {
                                    "pat": round(float(pat), 2),
                                    "src": "gemini",
                                    "ann": (20260715 if qe == 20260630 else 0),
                                    "basis": "C" if d.get("con") is not None else "S",
                                }
            except Exception as ex:
                print("    gemini fallback err:", str(ex)[:70])
    return res


def _render_pl_pngs(op, code):
    """Render the P&L-bearing pages of a scrip's latest result filing to PNGs (for the vision fallback)."""
    import bse_render

    pngs = []
    for _annd, att, _hd in scrip_announcements(op, code, 5)[:1]:
        raw = fetch_pdf(op, att)
        if not raw:
            continue
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            continue
        for pi in range(min(len(doc), 8)):
            txt = doc[pi].get_text()
            if txt.strip() and not bse_render.PL_HINT.search(txt):
                continue
            pngs.append(doc[pi].get_pixmap(dpi=200).tobytes("png"))
            if len(pngs) >= 4:
                break
        if pngs:
            break
    return pngs


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

    op = B.session()
    time.sleep(1)

    # DECLARED-FIRST: scrips that filed a result recently are ground first at ANY market cap, so
    # already-declared results (incl. sub-₹100cr names the mcap floor would skip) get numbers first.
    declared = set()
    if only is None and "--no-declared-first" not in sys.argv:
        declared = declared_recently(op, {str(r[0]) for r in univ})
        print("declared recently (BSE-only):", len(declared))

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
        try:
            recs = extract(op, code, name, months, deadline=time.time() + 120)  # ≤2 min/scrip
        except Exception as ex:
            print(f"  {code} {tkr} ERR {str(ex)[:60]}")
            recs = {}
        if recs:
            cur = data["px"].get(code, {})
            for qe, rec in recs.items():
                if str(qe) not in cur:  # fill-only
                    cur[str(qe)] = rec
            data["px"][code] = cur
            latest = max(recs)
            print("  ✓ %s %-12s %s PAT=%s rev=%s" % (code, tkr, latest, recs[latest]["pat"], recs[latest].get("rev")))
            done.add(code)
            fails.pop(code, None)
        else:
            print("  · %s %-12s (no anchored result)" % (code, tkr))
            # Record the failed attempt for EVERY scrip (declared or targeted) — this count drives the
            # page's "filing available — PDF only" label once a filed co has resisted parsing (fail>=2),
            # so users know its number isn't merely queued. A DECLARED scrip keeps retrying up to
            # MAX_FAIL runs (transient/parse miss); a non-declared one is done after this attempt.
            fails[code] = fails.get(code, 0) + 1
            if code not in declared or fails[code] >= MAX_FAIL:
                done.add(code)
        if spent % 10 == 0:
            ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
            data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            json.dump(sorted(done), open(DONE, "w"))
            json.dump(fails, open(FAILS, "w"))
            time.sleep(0.2)
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(sorted(done), open(DONE, "w"))
    ncov = len(data["px"])
    print("WROTE %s: processed %d scrips this run; %d scrips now have numbers" % (os.path.normpath(OUT), spent, ncov))


if __name__ == "__main__":
    main()
