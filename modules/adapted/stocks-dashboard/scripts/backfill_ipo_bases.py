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
"""AUTOMATIC year-ago / preceding-quarter base fill for NEWLY-LISTED stocks (IPOs, NSE migrations,
demerger listings) — so profit-growth YoY% works for them like it does for every established stock.

WHY: NSE integrated-filing XBRLs carry ONLY the current quarter (no comparative context), so a
newly-listed company enters sf_fundamentals.json with quarters but NO year-ago bases -> YoY% blank
on the site (runbook "Recent-IPO year-ago bases"). The bases ARE public: every results PDF prints
comparative columns (preceding 3 months + year-ago 3 months + YTD + FY) — the same columns
Trendlyne reads. This script extracts them, ANCHOR-VERIFIED, and fills them in. Fully unattended
(free): PyMuPDF text layer first, Gemini vision (free tier, GEMINI_API_KEY) for scanned filings.

  1. CANDIDATES — symbols whose EARLIEST stored quarter is recent (default: within ~16 months):
                  that's a new listing / new-to-NSE name. Insurers excluded (own pipeline).
  2. TARGETS    — for each stored quarter QE, the missing year-ago (QE-1y) and preceding (prev QE)
                  quarters. Each target is sourced from the filing PDF of a STORED quarter that
                  prints it as a comparative column.
  3. FETCH      — integrated-filing-results pdf_attach when real; else the corporate-announcements
                  attachment (index=equities, then =sme for pre-migration filings), result-filing
                  filtered, identity-guarded (company name must appear in the PDF).
  4. READ+ANCHOR (never guesses):
       text: parse column header DATES (x-positions) + the "Profit after tax" / owners /
             "Revenue from operations" rows; map numbers to columns by x. ACCEPT only when, under
             ONE unit scale (cr/million/lakh/thousand/rupees), the CURRENT-quarter column matches
             our stored XBRL value (and the preceding column too, when we have it stored) within
             max(3%, Rs 2cr). The matched scale converts the comparative columns.
       vision: scanned/garbled filings -> render P&L pages, Gemini reads cur/prec/yago (std+con,
             owners-attributable), then the SAME cur-anchor gate applies. No key -> cell is skipped
             (queued in the skip file with why="vision"; CI has GEMINI_API_KEY, so it drains there).
  5. APPLY      — fill-only: PAT into docs/sf_fundamentals.json + scripts/fundamentals.json
                  (ann=None -> fill_ann_dates.py stamps the SEBI deadline next workflow step);
                  revenue + PAT mirror into docs/sf_revop.json + scripts/revop_fundamentals.json.
                  Every fill is journaled in scripts/ipo_base_fills.json (audit + --reapply after a
                  full rebuild); failures tracked in scripts/_ipo_base_skips.json (retry-capped).

Run:
  python -X utf8 scripts/backfill_ipo_bases.py                    # nightly cron mode
  python -X utf8 scripts/backfill_ipo_bases.py --dry-run          # report, no writes
  python -X utf8 scripts/backfill_ipo_bases.py --only DTIL,ONIDA  # bypass recency cutoff
  python -X utf8 scripts/backfill_ipo_bases.py --reapply          # re-assert ledger (post-rebuild)

Out of scope (documented): BSE-only listings (no NSE announcements; the BSE OCR grind owns them),
operating-profit bases (needs 4-row derivation; rev+PAT cover the site's YoY), quarters no filing
ever printed (company listed too recently to have filed — fills arrive with its next filing).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import itertools

import build_fundamentals as B
import fitz
import gemini_vision as GV

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS_FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SRC_FUND = os.path.join(HERE, "fundamentals.json")
DOCS_REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
SRC_REVOP = os.path.join(HERE, "revop_fundamentals.json")
LEDGER = os.path.join(HERE, "ipo_base_fills.json")
SKIPS = os.path.join(HERE, "_ipo_base_skips.json")
FLAG = os.path.join(ROOT, "docs", ".fund_updated")

RECENT_DAYS = 480  # candidate = earliest stored quarter within this window
MAX_PDF_MB = 45  # bigger = annual-report dump; even vision rendering is wasteful
SKIP_CAP = 5  # attempts per (sym, target, source-qe) before perma-skip
DIVS = (1.0, 10.0, 100.0, 10000.0, 1e7)  # crore, million, lakh, thousand, rupees -> crore

INSURERS = {
    "LICI",
    "SBILIFE",
    "HDFCLIFE",
    "ICICIPRULI",
    "ICICIGI",
    "GICRE",
    "NIACL",
    "STARHEALTH",
    "GODIGIT",
    "NIVABUPA",
    "MFSL",
}

MON = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}


# ---------- quarter arithmetic ----------
def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}[md]


def yago(qe):
    return qe - 10000


def qe_label(qe):
    names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return "%d %s %d" % (qe % 100, names[(qe // 100) % 100], qe // 10000)


# ---------- stored-value lookups ----------
def fund_row(fund, sym, qe):
    return next((r for r in fund.get(sym, []) if r[0] == qe), None)


def pat_stored(fund, sym, qe):
    r = fund_row(fund, sym, qe)
    return (r[1], r[3]) if r else (None, None)  # (std, con)


def rev_stored(revop, sym, qe):
    rr = (revop.get(sym) or {}).get(str(qe))
    return (rr[0], rr[1]) if rr else (None, None)  # (std, con)


# ---------- NSE fetch ----------
def nse_get_json(url, jar, ref):
    h = {"User-Agent": B.UA, "Accept": "application/json", "Referer": ref}
    return json.loads(B._get(url, headers=h, jar=jar, timeout=60))


def integrated_rows(sym, jar):
    u = f"https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly&symbol={sym}"
    try:
        jb = nse_get_json(u, jar, "https://www.nseindia.com/companies-listing/corporate-filings-financial-results")
        return jb.get("data", jb if isinstance(jb, list) else [])
    except Exception as e:
        print(f"  {sym}: integrated list err: {str(e)[:80]}")
        return []


def qe_from_ann(a):
    y, m = a // 10000, (a // 100) % 100
    if 7 <= m <= 9:
        return y * 10000 + 630
    if 10 <= m <= 12:
        return y * 10000 + 930
    if 1 <= m <= 3:
        return (y - 1) * 10000 + 1231
    if 4 <= m <= 6:
        return y * 10000 + 331
    return 0


_ANN_GOOD = re.compile(r"financial result|integrated filing|outcome of board", re.IGNORECASE)
_ANN_BAD = re.compile(
    r"newspaper|analyst|investor (presentation|meet)|press release|transcript"
    r"|schedule|earnings call|record date|dividend only",
    re.IGNORECASE,
)


def _ddmmyyyy(qe, plus):
    y, m = qe // 10000, (qe // 100) % 100
    dt = datetime.date(y, m, 28) + datetime.timedelta(days=plus)
    return "%02d-%02d-%04d" % (dt.day, dt.month, dt.year)


def announcement_pdfs(sym, qe, jar):
    """Yield (url, size_mb) for result-filing attachments mapping to quarter qe (equities then sme)."""
    cands = []
    for idx in ("equities", "sme"):
        u = (
            f"https://www.nseindia.com/api/corporate-announcements?index={idx}&symbol={sym}"
            f"&from_date={_ddmmyyyy(qe, 5)}&to_date={_ddmmyyyy(qe, 170)}"
        )
        try:
            rows = nse_get_json(u, jar, "https://www.nseindia.com/companies-listing/corporate-filings-announcements")
            if isinstance(rows, dict):
                rows = rows.get("data", []) or []
        except Exception:
            rows = []
        for rec in rows:
            desc = str(rec.get("desc", ""))
            blob = desc + " " + str(rec.get("attchmntText", ""))
            f = rec.get("attchmntFile", "") or ""
            if not f.lower().endswith(".pdf"):
                continue
            if not _ANN_GOOD.search(blob) or _ANN_BAD.search(desc):
                continue
            a = B.iso(str(rec.get("an_dt", "")) or str(rec.get("sort_date", "")))
            if a and qe_from_ann(int(a)) != qe:
                continue
            m = re.match(r"([\d.]+)\s*(KB|MB|GB)", str(rec.get("fileSize") or rec.get("attFileSize") or ""))
            sz = float(m.group(1)) * {"KB": 0.001, "MB": 1, "GB": 1000}[m.group(2)] if m else 0
            cands.append((sz, f))
        if cands:
            break  # equities hit — no need to query sme
    seen = set()
    out = []
    for sz, f in sorted(cands, reverse=True):
        if f not in seen:
            seen.add(f)
            out.append((f, sz))
    return out[:4]


def fetch_pdf(url):
    try:
        raw = B._get(
            url, headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=180, binary=True
        )
        return raw if raw[:4] == b"%PDF" else None
    except Exception:
        return None


# ---------- text-layer parsing ----------
_NUMTOK = re.compile(r"^\(?-?[\d,]+\.\d{1,2}\)?$|^\(?-?[\d,]{4,}\)?$")  # decimals, or >=4-digit ints
_PAT_ROW = re.compile(r"profit.{0,28}after tax|profit.{0,25}for the (period|quarter|year)", re.IGNORECASE)
_OWN = re.compile(r"(owners|equity ?holders|equityholders|attributab)", re.IGNORECASE)
_BAD_ROW = re.compile(
    r"before tax|comprehensive|segment|exceptional|carried to|balance sheet|margin"
    r"|per share|earnings per|eps\b|ratio|paid.?up|dividend|non-controlling"
    r"|minority|reserve|tax expense|deferred",
    re.IGNORECASE,
)
_REV_ROW = re.compile(r"^[ivx0-9 .()|]{0,8}(revenue|income) from operations", re.IGNORECASE)

_DATE_PATS = [
    re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$"),  # 31/03/2026, 31.03.2026
    re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[ ]?([A-Za-z]{3,9})[,.']*[ ]?(\d{4})$"),  # 31 March 2026
    re.compile(r"^([A-Za-z]{3,9})[ ](\d{1,2})(?:st|nd|rd|th)?[,.']*[ ]?(\d{4})$"),  # March 31, 2026
    re.compile(r"^(\d{1,2})[.-]([A-Za-z]{3})[.-](\d{2,4})$"),  # 31-Mar-26
    re.compile(r"^(\d{2})(\d{2})(\d{4})$"),  # 31032026 (bare ddmmyyyy)
]


def _parse_date(txt):
    t = txt.strip().strip(",")
    for i, p in enumerate(_DATE_PATS):
        m = p.match(t)
        if not m:
            continue
        try:
            if i == 0:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif i == 1:
                d, mo, y = int(m.group(1)), MON.get(m.group(2)[:3].lower(), 0), int(m.group(3))
            elif i == 2:
                d, mo, y = int(m.group(2)), MON.get(m.group(1)[:3].lower(), 0), int(m.group(3))
            elif i == 4:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), MON.get(m.group(2)[:3].lower(), 0), int(m.group(3))
                y += 2000 if y < 100 else 0
            if 1 <= mo <= 12 and 2000 < y < 2100 and 1 <= d <= 31:
                return y * 10000 + mo * 100 + d
        except Exception:
            pass
    return None


def _numtok(t):
    """Number-cell token, tolerating trailing punctuation ('(1,062),'). Returns cleaned str or None.
    Loose on purpose: a garbled OCR digit can slip through here — the stored-value ANCHOR is the gate."""
    t = t.strip().rstrip(".,;:|")
    return t if _NUMTOK.match(t) else None


def _tv(w):
    t = _numtok(w)
    if t is None:
        return None
    neg = t.startswith(("(", "-"))
    t = t.replace(",", "").replace("(", "").replace(")", "").lstrip("-")
    try:
        v = float(t)
        return -v if neg else v
    except Exception:
        return None


def _lines(words):
    ws = sorted(words, key=lambda w: (round(w[1]), w[0]))
    out, cur, cy = [], [], None
    for w in ws:
        if cy is None or abs(w[1] - cy) <= 4:
            cur.append(w)
        else:
            out.append(cur)
            cur = [w]
        cy = w[1]
    if cur:
        out.append(cur)
    return [sorted(l, key=lambda w: w[0]) for l in out]


def _page_dates(lines, below_y=None):
    """All (x_center, yyyymmdd) header dates on the page (joins up to 3 adjacent words), x-ordered."""
    found = []
    for ln in lines:
        if below_y is not None and ln and ln[0][1] > below_y:
            continue
        n = len(ln)
        for i in range(n):
            for k in (3, 2, 1):
                if i + k > n:
                    continue
                seg = ln[i : i + k]
                d = _parse_date(" ".join(w[4] for w in seg))
                if d:
                    xc = sum((w[0] + w[2]) / 2 for w in seg) / k
                    found.append((xc, d))
                    break
    # de-dup near-identical x (same date token caught by two window sizes)
    found.sort()
    out = []
    for xc, d in found:
        if out and abs(out[-1][0] - xc) < 6 and out[-1][1] == d:
            continue
        out.append((xc, d))
    return out


def _metric_rows(lines, all_words):
    """[(kind, isOwners, [(x_center, value), ...])] for PAT / REV candidate rows."""
    numw = [w for w in all_words if _numtok(w[4])]
    out = []
    for ln in lines:
        label = " ".join(w[4] for w in ln).lower()
        kind = None
        if _REV_ROW.search(label) and "other" not in label[:30]:
            kind = "rev"
        elif (_PAT_ROW.search(label) or _OWN.search(label)) and not _BAD_ROW.search(label):
            kind = "pat"
        if not kind:
            continue
        cells = [((w[0] + w[2]) / 2, _tv(w[4])) for w in ln if _numtok(w[4])]
        cells = [(x, v) for x, v in cells if v is not None]
        if len(cells) < 2:  # figures on a nearby baseline — band-merge
            ly = sum(w[1] for w in ln) / len(ln)
            lx = max((w[2] for w in ln if not _numtok(w[4])), default=ln[0][0])
            band = [w for w in numw if abs((w[1] + w[3]) / 2 - ly) <= 8 and w[0] > lx - 2]
            cells = [((w[0] + w[2]) / 2, _tv(w[4])) for w in sorted(band, key=lambda w: w[0])]
            cells = [(x, v) for x, v in cells if v is not None]
        if len(cells) >= 2:
            out.append((kind, bool(_OWN.search(label)), cells))
    return out


def _map_columns(dates, cells):
    """Assign each numeric cell to the nearest date column (unique). None on ambiguity — INCLUDING
    any figure cell inside the column zone that maps to no header date. (VIKRAMSOLR lesson: a header
    date that fails to parse must reject the row, not silently shift 'preceding' onto the FY column.)"""
    if not dates or not cells:
        return None
    xs = [x for x, _ in dates]
    gaps = [b - a for a, b in itertools.pairwise(xs)] or [120.0]
    tol = max(28.0, min(gaps) * 0.6)
    col_zone = min(xs) - tol  # figures start at the first header column
    used = {}
    for x, v in cells:
        j = min(range(len(dates)), key=lambda i: abs(dates[i][0] - x))
        if abs(dates[j][0] - x) > tol:
            if x > col_zone:
                return None  # unaccounted figure column — unsafe mapping
            continue  # left-side stray (label-embedded number)
        if j in used:
            return None  # two numbers claim one column — ambiguous
        used[j] = v
    return used or None


def parse_pdf_text(pdf, ident_tokens):
    """-> list of page parses: {'con': bool, 'dates': [(x,d)...], 'rows': [(kind,isown,cells)...]}
    None on identity mismatch (wrong company's PDF)."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return None
    N = min(len(doc), 40)
    texts = [doc[p].get_text() for p in range(N)]
    full = " ".join(texts)
    if ident_tokens and full.strip() and not any(t.upper() in full.upper() for t in ident_tokens):
        return None
    pages = []
    con = False
    for p in range(N):
        low = texts[p].lower()
        if "consolidated" in low:
            con = True
        elif re.search(r"standalone\s+(statement|financial|results|unaudited|audited|ind)", low):
            con = False
        if not _PAT_ROW.search(texts[p]):
            continue
        words = doc[p].get_text("words")
        lines = _lines(words)
        rows = _metric_rows(lines, words)
        if not rows:
            continue
        first_row_y = min(
            (min(w[1] for w in ln) for ln in lines if _PAT_ROW.search(" ".join(x[4] for x in ln).lower())), default=None
        )
        dates = _page_dates(lines, below_y=first_row_y)
        pages.append(
            {
                "con": ("consolidated" in low),
                "std_hint": ("standalone" in low),
                "con_flag": con,
                "dates": dates,
                "rows": rows,
            }
        )
    return pages


def _close(a, b, tol_pct=0.03, tol_abs=2.0):
    return a is not None and b is not None and abs(a - b) <= max(abs(b) * tol_pct, tol_abs)


def columns_for(page, qe):
    """Column-index map {'cur': i, 'prec': i|None, 'yago': i|None} by FIRST-occurrence of each header
    date (3-month columns precede YTD/FY in the SEBI format, so leftmost wins).
    ORDERING GUARD (VIKRAMSOLR lesson #2 — a filing whose header MISPRINTS the preceding-quarter date
    makes 'first occurrence' land on the FY column): structurally, cur < prec < yago < YTD/FY. A
    'prec' at/right of 'yago', or a 'yago' at/left of 'cur', is impossible — drop that column."""
    first = {}
    for i, (_x, d) in enumerate(page["dates"]):
        first.setdefault(d, i)
    cur = first.get(qe)
    if cur is None:
        return None
    prec, yg = first.get(prevq(qe)), first.get(yago(qe))
    if yg is not None and (yg <= cur or yg > cur + 2):
        yg = None  # yago lives in the 3m block: cur+1 / cur+2
    if prec is not None and (prec <= cur or (yg is not None and prec >= yg)):
        prec = None
    if prec is not None and yg is None and prec != cur + 1:
        prec = None  # prec must adjoin cur when yago absent
    return {"cur": cur, "prec": prec, "yago": yg}


def extract_anchored(pages, qe, want_con, cur_pat, prec_pat, cur_rev):
    """Try every parsed page/row of the wanted basis; return
    {'pat': {'prec': v|None, 'yago': v|None}, 'rev': {...}, 'div': d} once the CURRENT column matches
    the stored value under one scale (and the PRECEDING column too when we know it). None if nothing anchors."""
    if cur_pat is None:
        return None
    strong = abs(cur_pat) >= 1.0 or prec_pat is not None
    if not strong:
        return None  # anchor value too weak to trust alone
    for page in pages:
        basis_con = page["con"] or (page["con_flag"] and not page["std_hint"])
        if basis_con != want_con:
            continue
        cols = columns_for(page, qe)
        if not cols:
            continue
        pat_rows = sorted(
            [r for r in page["rows"] if r[0] == "pat"], key=lambda r: (not r[1],)
        )  # owners-labelled rows first
        for _, _isown, cells in pat_rows:
            m = _map_columns(page["dates"], cells)
            if not m or cols["cur"] not in m:
                continue
            raw_cur = m[cols["cur"]]
            for div in DIVS:
                if not _close(raw_cur / div, cur_pat):
                    continue
                if (
                    prec_pat is not None
                    and cols["prec"] is not None
                    and cols["prec"] in m
                    and not _close(m[cols["prec"]] / div, prec_pat)
                ):
                    continue
                out = {"pat": {}, "rev": {}, "div": div}
                for k in ("prec", "yago"):
                    ci = cols[k]
                    out["pat"][k] = round(m[ci] / div, 2) if ci is not None and ci in m else None
                # revenue row on the same page, SAME scale; verified against stored rev when we have it
                for _, _o, rcells in [r for r in page["rows"] if r[0] == "rev"]:
                    rm = _map_columns(page["dates"], rcells)
                    if not rm or cols["cur"] not in rm:
                        continue
                    if cur_rev is not None and not _close(rm[cols["cur"]] / div, cur_rev):
                        continue
                    for k in ("prec", "yago"):
                        ci = cols[k]
                        out["rev"][k] = round(rm[ci] / div, 2) if ci is not None and ci in rm else None
                    break
                return out
    return None


# ---------- vision fallback ----------
_PL_HINT = re.compile(
    r"profit.{0,28}after tax|statement of (un)?audited|financial results"
    r"|revenue from operations|profit before tax",
    re.IGNORECASE,
)


def render_pngs(pdf, ident_tokens):
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return None
    N = min(len(doc), 40)
    texts = [doc[p].get_text() for p in range(N)]
    full = " ".join(texts)
    if ident_tokens and full.strip() and not any(t.upper() in full.upper() for t in ident_tokens):
        return None
    pages = [p for p in range(N) if _PL_HINT.search(texts[p]) or (not texts[p].strip() and doc[p].get_images())]
    if not pages:
        return None
    if len(pages) > 6:
        pages = [pages[round(i * (len(pages) - 1) / 5)] for i in range(6)]
    return [doc[p].get_pixmap(dpi=160).tobytes("png") for p in sorted(set(pages))]


VISION_LEFT = [60]  # per-run cap on Gemini calls — keeps the shared free-tier daily quota alive
# for the insurer step and for tomorrow's run (~200 RPD on flash free tier)


def vision_ok():
    return os.environ.get("GEMINI_API_KEY") and not GV.quota_dead() and VISION_LEFT[0] > 0


def vision_extract(pdf, company, sym, qe, fund, ident_tokens):
    if not vision_ok():
        return None
    VISION_LEFT[0] -= 1
    pngs = render_pngs(pdf, ident_tokens)
    if not pngs:
        return None
    r = GV.read_corp_results(company or sym, qe_label(qe), qe_label(prevq(qe)), qe_label(yago(qe)), pngs)
    if not r or not r.get("ok") or not r.get("company_matches"):
        return None
    cs, cc = pat_stored(fund, sym, qe)
    out = {}
    for basis, cur_stored in (("std", cs), ("con", cc)):
        if cur_stored is None:
            continue
        if not _close(r["cur"].get(basis), cur_stored, 0.03, 2.0):
            continue  # anchor gate
        out[basis] = {"prec": r["prec"].get(basis), "yago": r["yago"].get(basis)}
    return out or None


# ---------- audit setters (overwrite/clear — used ONLY by --audit) ----------
def set_pat(funds, sym, qe, basis, val):
    i = 1 if basis == "std" else 3
    for fund in funds:
        row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
        if row is None:
            continue
        row[i] = round(val, 2) if val is not None else None
        if val is None:
            row[i + 1] = None  # clear the stamped deadline too


def set_rev(revops, sym, qe, basis, rev="keep", pat="keep"):
    ri, pi = (0, 4) if basis == "std" else (1, 5)
    for revop in revops:
        rr = (revop.get(sym) or {}).get(str(qe))
        if not rr:
            continue
        if rev != "keep":
            rr[ri] = round(rev, 2) if rev is not None else None
        if pat != "keep":
            rr[pi] = round(pat, 2) if pat is not None else None


# ---------- fill helpers (fill-only, both mirrors) ----------
def fill_pat(funds, sym, qe, basis, val):
    changed = False
    for fund in funds:
        rows = fund.setdefault(sym, [])
        row = next((r for r in rows if r[0] == qe), None)
        if row is None:
            row = [qe, None, None, None, None]
            rows.append(row)
            rows.sort(key=lambda r: r[0])
        i = 1 if basis == "std" else 3
        if row[i] is None and val is not None:
            row[i] = round(val, 2)
            changed = True
    return changed


def fill_rev(revops, sym, qe, basis, rev=None, pat=None):
    changed = False
    for revop in revops:
        d = revop.setdefault(sym, {})
        rr = d.get(str(qe)) or [None] * 6 + [0, None, None]
        if len(rr) < 9:
            rr += [None] * (9 - len(rr))
        ri, pi = (0, 4) if basis == "std" else (1, 5)
        if rev is not None and rr[ri] is None:
            rr[ri] = round(rev, 2)
            changed = True
        if pat is not None and rr[pi] is None:
            rr[pi] = round(pat, 2)
            changed = True
        d[str(qe)] = rr
    return changed


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--days", type=int, default=RECENT_DAYS)
    ap.add_argument("--limit", type=int, default=0, help="max symbols to WORK (fetch PDFs for) this run; 0 = no cap")
    ap.add_argument(
        "--max-minutes",
        type=float,
        default=0,
        help="stop cleanly after this many minutes (CI job-timeout safety); 0 = no cap",
    )
    ap.add_argument(
        "--vision-cap",
        type=int,
        default=60,
        help="max Gemini calls this run (protects the shared free-tier daily quota)",
    )
    ap.add_argument("--reapply", action="store_true", help="re-assert the fill ledger (after a full rebuild)")
    ap.add_argument(
        "--audit", action="store_true", help="re-extract every text-sourced ledger cell and fix/revert mismatches"
    )
    args = ap.parse_args()

    fund_docs = json.load(open(DOCS_FUND))
    fund_src = json.load(open(SRC_FUND)) if os.path.exists(SRC_FUND) else None
    revop_docs = json.load(open(DOCS_REVOP)) if os.path.exists(DOCS_REVOP) else {}
    revop_src = json.load(open(SRC_REVOP)) if os.path.exists(SRC_REVOP) else None
    funds = [f for f in (fund_docs, fund_src) if f is not None]
    revops = [r for r in (revop_docs, revop_src) if r is not None]
    ledger = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    today = datetime.date.today().isoformat()

    if args.reapply:
        n = 0
        for sym, cells in ledger.items():
            for qs, c in cells.items():
                qe = int(qs)
                for basis in ("std", "con"):
                    if c.get("pat" + basis.capitalize()) is not None:
                        n += fill_pat(funds, sym, qe, basis, c["pat" + basis.capitalize()])
                    fill_rev(
                        revops, sym, qe, basis, c.get("rev" + basis.capitalize()), c.get("pat" + basis.capitalize())
                    )
        print("reapplied ledger: %d PAT cells re-asserted" % n)
        if not args.dry_run and n:
            _write_all(funds, revops)
            open(FLAG, "w").write(today)
        return

    if args.audit:
        jar = B.nse_jar()
        ok = fixed = reverted = 0
        for sym in sorted(ledger):
            cells = ledger[sym]
            by_src = {}
            for qs, c in cells.items():
                if c.get("via") == "text" and c.get("srcQe"):
                    by_src.setdefault(c["srcQe"], []).append((int(qs), c))
            if not by_src:
                continue
            irows = integrated_rows(sym, jar)
            company = next(
                (r.get("cmName") or r.get("smName") for r in irows if r.get("cmName") or r.get("smName")), sym
            )
            ident = [w for w in re.split(r"[^A-Za-z]+", company or "") if len(w) > 3][:2] or [sym]
            for srcqe, tgts in sorted(by_src.items()):
                url = tgts[0][1].get("src")
                pdf = fetch_pdf(url) if url else None
                pages = parse_pdf_text(pdf, ident) if pdf else None
                cs, cc = pat_stored(fund_docs, sym, srcqe)
                # circular-anchor guard: don't anchor on a preceding value WE wrote
                self_prec = str(prevq(srcqe)) in cells
                ps, pc = (None, None) if self_prec else pat_stored(fund_docs, sym, prevq(srcqe))
                rs, rc = rev_stored(revop_docs, sym, srcqe)
                res = {}
                for basis, cur, prec, crev in (("std", cs, ps, rs), ("con", cc, pc, rc)):
                    res[basis] = extract_anchored(pages, srcqe, basis == "con", cur, prec, crev) if pages else None
                for t, c in tgts:
                    key = "prec" if t == prevq(srcqe) else "yago"
                    for basis in ("std", "con"):
                        a = res.get(basis)
                        bk, rk = "pat" + basis.capitalize(), "rev" + basis.capitalize()
                        for _k in (bk, rk):  # scrub legacy None-valued keys
                            if c.get(_k, "x") is None:
                                c.pop(_k)
                        if bk in c:
                            new = a["pat"].get(key) if a else None
                            if new is not None and abs(new - c[bk]) <= 0.011:
                                ok += 1
                            elif new is not None:
                                print("  AUDIT FIX %s %d %s pat: %s -> %s" % (sym, t, basis, c[bk], new))
                                set_pat(funds, sym, t, basis, new)
                                set_rev(revops, sym, t, basis, "keep", new)
                                c[bk] = new
                                fixed += 1
                            else:
                                print("  AUDIT REVERT %s %d %s pat: %s -> blank (re-queued)" % (sym, t, basis, c[bk]))
                                set_pat(funds, sym, t, basis, None)
                                set_rev(revops, sym, t, basis, "keep", None)
                                c.pop(bk)
                                reverted += 1
                        if rk in c:
                            rnew = a["rev"].get(key) if a else None
                            if rnew is not None and abs(rnew - c[rk]) <= 0.011:
                                ok += 1
                            elif rnew is not None:
                                print("  AUDIT FIX %s %d %s rev: %s -> %s" % (sym, t, basis, c[rk], rnew))
                                set_rev(revops, sym, t, basis, rnew, "keep")
                                c[rk] = rnew
                                fixed += 1
                            else:
                                print("  AUDIT REVERT %s %d %s rev: %s -> blank" % (sym, t, basis, c[rk]))
                                set_rev(revops, sym, t, basis, None, "keep")
                                c.pop(rk)
                                reverted += 1
            for qs in [q for q, c in cells.items() if not any(k.startswith(("pat", "rev")) for k in c)]:
                cells.pop(qs)
        print("AUDIT DONE. ok=%d fixed=%d reverted=%d" % (ok, fixed, reverted))
        if not args.dry_run and (fixed or reverted):
            _write_all(funds, revops)
            json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
            open(FLAG, "w").write(today)
        return

    cutoff = int((datetime.date.today() - datetime.timedelta(days=args.days)).strftime("%Y%m%d"))
    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}
    cands = []
    for sym, rows in fund_docs.items():
        if sym in INSURERS or not rows:
            continue
        if only and sym not in only:
            continue
        if not only and min(r[0] for r in rows) < cutoff:
            continue
        cands.append(sym)
    print("new-listing candidates (earliest quarter >= %d): %d" % (cutoff, len(cands)))

    jar = B.nse_jar()
    VISION_LEFT[0] = args.vision_cap
    t0 = time.time()
    filled = skipped = worked = 0
    flushed = [0]

    def flush():
        """Incremental persist so a timeout (CI job cap) can't lose completed symbols' fills."""
        if args.dry_run or filled == flushed[0]:
            return
        _write_all(funds, revops)
        json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
        json.dump(skips, open(SKIPS, "w"), indent=1)
        open(FLAG, "w").write(today)
        flushed[0] = filled

    # newest listings first — they're the ones visible on the site right now
    cands.sort(key=lambda s: (-min(r[0] for r in fund_docs[s]), s))
    for sym in cands:
        rows = fund_docs[sym]
        qes = sorted(r[0] for r in rows)

        # outstanding target = quarter with NO PAT at all on either basis (absent or both None)
        def missing(t):
            r = fund_row(fund_docs, sym, t)
            return r is None or (r[1] is None and r[3] is None)

        plan = {}  # source filing qe -> set of wanted targets
        for qe in qes:
            for t in (prevq(qe), yago(qe)):
                if missing(t):
                    plan.setdefault(qe, set()).add(t)
        if not plan:
            continue

        def _capped(qe):
            sk = skips.get("%s|%d" % (sym, qe), {})
            if sk.get("why") == "vision":
                return not vision_ok()  # vision-queued: actionable only while Gemini is available
            return sk.get("n", 0) >= SKIP_CAP

        if all(_capped(qe) for qe in plan):
            continue  # nothing actionable this run
        if args.limit and worked >= args.limit:
            print("(--limit %d reached — remaining symbols next run)" % args.limit)
            break
        if args.max_minutes and (time.time() - t0) > args.max_minutes * 60:
            print(f"(--max-minutes {args.max_minutes:.0f} reached — stopping cleanly, remaining symbols next run)")
            break
        worked += 1
        irows = integrated_rows(sym, jar)
        company = next((r.get("cmName") or r.get("smName") for r in irows if r.get("cmName") or r.get("smName")), sym)
        ident = [w for w in re.split(r"[^A-Za-z]+", company or "") if len(w) > 3][:2] or [sym]
        print(
            "%s (%s): %d source filings for %d missing base cells"
            % (sym, company, len(plan), len(set().union(*plan.values())))
        )

        for qe in sorted(plan, reverse=True):
            wanted = {t for t in plan[qe] if missing(t)}
            if not wanted:
                continue
            skey_base = "%s|%d" % (sym, qe)
            sk = skips.get(skey_base, {})
            if sk.get("n", 0) >= SKIP_CAP and sk.get("why") != "vision":
                continue
            if sk.get("why") == "vision" and not os.environ.get("GEMINI_API_KEY"):
                continue
            # -- collect candidate PDFs: integrated pdf_attach, else announcements
            urls = []
            for r in irows:
                if B.iso(r.get("qe_Date")) != str(qe):
                    continue
                pa = r.get("pdf_attach") or ""
                m = re.match(r"([\d.]+)\s*(Bytes|KB|MB)", str(r.get("attFileSize") or ""))
                sz = float(m.group(1)) * {"Bytes": 1e-6, "KB": 0.001, "MB": 1}[m.group(2)] if m else 0
                if pa.startswith("http") and not pa.endswith("/null") and sz > 0.01:
                    urls.append((pa, sz))
            urls += announcement_pdfs(sym, qe, jar)
            if not urls:
                skips[skey_base] = {"n": sk.get("n", 0) + 1, "why": "no result PDF found", "last": today}
                skipped += 1
                print("  %d: SKIP — no result PDF found" % qe)
                continue

            got = None
            via = None
            used_url = None
            cs, cc = pat_stored(fund_docs, sym, qe)
            ps, pc = pat_stored(fund_docs, sym, prevq(qe))
            rs, rc = rev_stored(revop_docs, sym, qe)
            for url, sz in urls:
                if sz > MAX_PDF_MB:
                    skips[skey_base] = {"n": sk.get("n", 0) + 1, "why": f"pdf too big ({sz:.0f} MB)", "last": today}
                    continue
                pdf = fetch_pdf(url)
                if not pdf:
                    continue
                pages = parse_pdf_text(pdf, ident)
                if pages is None:
                    continue  # identity mismatch — wrong company's PDF
                res = {}
                for basis, cur, prec, crev in (("std", cs, ps, rs), ("con", cc, pc, rc)):
                    a = extract_anchored(pages, qe, basis == "con", cur, prec, crev)
                    if a:
                        res[basis] = a
                if res:
                    got, via, used_url = res, "text", url
                    break
                v = vision_extract(pdf, company, sym, qe, fund_docs, ident)
                if v:
                    got = {b: {"pat": v[b], "rev": {}, "div": None} for b in v}
                    via, used_url = "gemini", url
                    break
            if not got:
                if not vision_ok():
                    # vision never actually looked (no key / quota dead / cap spent) — re-queue
                    # WITHOUT burning an attempt, else quota-dead nights perma-skip real cells
                    why, n = "vision", sk.get("n", 0)
                else:
                    why, n = "no anchor (text+vision)", sk.get("n", 0) + 1
                skips[skey_base] = {"n": n, "why": why, "last": today}
                skipped += 1
                print("  %d: SKIP — %s" % (qe, why))
                continue

            for t, key in ((prevq(qe), "prec"), (yago(qe), "yago")):
                if t not in wanted:
                    continue
                cell = ledger.setdefault(sym, {}).setdefault(str(t), {})
                any_fill = False
                for basis in ("std", "con"):
                    a = got.get(basis)
                    if not a:
                        continue
                    pv = a["pat"].get(key)
                    rv = a.get("rev", {}).get(key)
                    if pv is None and rv is None:
                        continue
                    if args.dry_run:
                        print(
                            "  WOULD FILL %s %d %s: pat=%s rev=%s (from %d filing, %s)"
                            % (sym, t, basis, pv, rv, qe, via)
                        )
                        any_fill = True
                        continue
                    ch1 = fill_pat(funds, sym, t, basis, pv) if pv is not None else False
                    ch2 = fill_rev(revops, sym, t, basis, rv, pv)
                    if ch1 or ch2:
                        if pv is not None:
                            cell["pat" + basis.capitalize()] = pv
                        if rv is not None:
                            cell["rev" + basis.capitalize()] = rv
                        any_fill = True
                if any_fill:
                    cell.update({"src": used_url, "srcQe": qe, "via": via, "on": today})
                    filled += 1
                    print(
                        "  FILLED %s %d from the %d filing (%s): %s"
                        % (sym, t, qe, via, {k: v for k, v in cell.items() if k != "src"})
                    )
            skips.pop(skey_base, None)
        flush()

    if not args.dry_run:
        flush()
        json.dump(skips, open(SKIPS, "w"), indent=1)
    print("DONE. filled %d base cells, %d skips.%s" % (filled, skipped, " (dry-run)" if args.dry_run else ""))


def _write_all(funds, revops):
    for f, path in zip(funds, (DOCS_FUND, SRC_FUND), strict=False):
        tmp = path + ".tmp"
        json.dump(f, open(tmp, "w"), separators=(",", ":"))
        os.replace(tmp, path)
    for r, path in zip(revops, (DOCS_REVOP, SRC_REVOP), strict=False):
        tmp = path + ".tmp"
        json.dump(r, open(tmp, "w"), separators=(",", ":"))
        os.replace(tmp, path)


if __name__ == "__main__":
    main()
