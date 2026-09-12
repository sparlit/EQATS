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
"""Source documents for the per-stock INSIGHTS card (operating KPIs) — runbook §137.

The card shows business/operating metrics a company reports about itself (stores, subscribers,
ARPU, order book, branches, CASA, capacity, volumes …). Those numbers live in the company's OWN
filings on BSE, not in any XBRL, so this module is the document ladder:

  ip   Investor Presentation      (Company Update / Investor Presentation)   quarterly + FY tables
  pr   Press / Media Release       (Company Update / Press Release …)         quarterly KPIs in prose+tables
  res  Financial Results packet    (Result / Financial Results)              some cos bundle the PR/IP here
  ar   Annual Report               (AnnualReport_New API)                    full-year KPIs, 10+ years

BSE facts measured 2026-09-06 (do not assume — re-measure if a call returns 0 rows):
  * AnnSubCategoryGetData with strScrip=<code> answers only for a bounded window: 217 days
    (2026-02-01..09-06) returned rows, 12 months (2025-09-01..2026-09-06) returned 0 rows with NO
    error. list_docs() therefore walks 180-day windows back to `since` and pages each (50/page).
  * Rows carry ATTACHMENTNAME (a GUID .pdf) + Fld_Attachsize; the file lives under AttachLive,
    AttachHis or (old) CorpAttachment/<Y>/<M>; AnnPdfOpen.aspx?Pname= resolves the right base.
  * AnnualReport_New/w?scripcode= lists annual reports by FY with a direct PDFDownload URL.
Every download is validated on `%PDF-` magic + a size floor — a 162-byte body is BSE's 302 stub,
never a document (feedback-validate-downloads-not-exit-codes).
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPS = os.path.join(HERE, "bse_scrips.json")
CACHE = os.environ.get("KPI_DOC_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "kpi_docs")

HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
}
PACE = {"last": 0.0}
MIN_GAP = 0.6  # seconds between BSE calls — the per-IP quota is real (runbook §0, 162-byte 302)


def _get(url, timeout=60, binary=False):
    wait = MIN_GAP - (time.time() - PACE["last"])
    if wait > 0:
        time.sleep(wait)
    PACE["last"] = time.time()
    req = urllib.request.Request(url, headers=HDR)
    r = urllib.request.urlopen(req, timeout=timeout)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if binary else raw.decode("utf-8", "replace")


_SCRIPS = None


def scripcode(sym):
    """BSE scrip code for an NSE symbol via scripts/bse_scrips.json (None = not on BSE / unmapped)."""
    global _SCRIPS
    if _SCRIPS is None:
        _SCRIPS = json.load(open(SCRIPS, encoding="utf-8")).get("by_id", {})
    v = _SCRIPS.get(sym)
    return int(v) if v else None


CATALOG_VER = 5  # bump when KIND_RULES / classify() change — cached ledger catalogs are rebuilt
#                      v4 (2026-09-06): annual reports (kind `ar`) pulled into the ladder for the depth
#                      pass — every cached catalog rebuilds so already-read stocks resurface their unread
#                      annual reports (the multi-year business-profile series) for re-deepening.

KIND_RULES = [
    # (kind, regex over "SUBCATNAME | NEWSSUB | HEADLINE") — first match wins, so the noise kinds
    # come first: HDFC Bank's "Transcript of Earnings Call in relation to the … financial results"
    # matched `res` and a 1-page audio-recording notice was queued as a results packet (2026-09-06)
    ("tr", r"transcript|audio recording|video recording|webcast|audio/video|recording of"),
    ("news", r"newspaper|advertisement|publication of|trading window|closure of"),
    ("ip", r"investor presentation|earnings presentation|analyst presentation|investor deck"),
    ("pr", r"press release|media release|press meet"),
    ("ar", r"annual report"),
    ("res", r"financial result|results for (the )?quarter|unaudited .*results|audited .*results"),
    ("tr", r"transcript"),
    ("meet", r"analyst / investor meet|investor meet|analyst meet"),
]


def classify(row):
    txt = " | ".join(str(row.get(k) or "") for k in ("SUBCATNAME", "NEWSSUB", "HEADLINE"))
    low = txt.lower()
    # board-meeting intimations/outcomes mention "financial results" without carrying any — the
    # Result-category row holds the actual packet (measured 2026-09-06: RIL/KTKBANK intimations
    # were 1-page PDFs classified as `res`)
    if str(row.get("CATEGORYNAME") or "").lower().startswith("board meeting") or "intimation" in low:
        return None
    for kind, rx in KIND_RULES:
        if re.search(rx, low):
            return kind
    return None


def _ymd(d):
    return d.strftime("%Y%m%d")


def list_docs(sym, since="2015-04-01", until=None, kinds=("ip", "pr", "res", "ar"), verbose=False):
    """All BSE announcements of the wanted kinds for `sym`, newest first.
    Returns [{kind, date:'YYYY-MM-DD', title, att, size, cat, sub}] — att = ATTACHMENTNAME."""
    code = scripcode(sym)
    if not code:
        return []
    until = until or date.today()
    if isinstance(until, str):
        until = datetime.strptime(until, "%Y-%m-%d").date()
    lo = datetime.strptime(since, "%Y-%m-%d").date()
    out, seen = [], set()
    T = until
    while lo <= T:
        F = max(lo, T - timedelta(days=179))
        page = 1
        while page <= 40:
            url = (
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
                "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C&subcategory=-1"
                % (page, _ymd(F), code, _ymd(T))
            )
            try:
                j = json.loads(_get(url))
            except Exception as ex:
                print("  list_docs %s %s..%s p%d ERR %s" % (sym, F, T, page, str(ex)[:80]), file=sys.stderr)
                break
            rows = j.get("Table") or []
            for r in rows:
                kind = classify(r)
                att = r.get("ATTACHMENTNAME") or ""
                if not kind or kind not in kinds or not att.lower().endswith(".pdf"):
                    continue
                if att in seen:
                    continue
                seen.add(att)
                dt = (r.get("NEWS_DT") or "")[:10]
                title = max((str(r.get("NEWSSUB") or ""), str(r.get("HEADLINE") or "")), key=len).strip()
                out.append(
                    {
                        "kind": kind,
                        "date": dt,
                        "att": att,
                        "title": title[:160],
                        "size": int(r.get("Fld_Attachsize") or 0),
                        "cat": r.get("CATEGORYNAME"),
                        "sub": r.get("SUBCATNAME"),
                    }
                )
            if verbose:
                print("  %s %s..%s p%d rows=%d" % (sym, F, T, page, len(rows)))
            if len(rows) < 50:
                break
            page += 1
        T = F - timedelta(days=1)
    if "ar" in kinds:
        # AnnualReport_New lists 30+ years; keep only the recent window (FY >= since-year - 1). The
        # 5/10-year highlights tables in these recent reports already reach back a decade, so this
        # gives the depth without letting a megacap's 30 old reports hog the --next queue forever.
        ar_lo_fy = lo.year - 1
        for a in annual_reports(sym):
            if a["att"] not in seen and a.get("fy", 0) >= ar_lo_fy:
                seen.add(a["att"])
                out.append(a)
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def annual_reports(sym):
    """[{kind:'ar', date:'YYYY-03-31'-ish FY end, fy, url, att}] from AnnualReport_New (direct URLs)."""
    code = scripcode(sym)
    if not code:
        return []
    try:
        j = json.loads(_get("https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=%d" % code))
    except Exception as ex:
        print(f"  annual_reports {sym} ERR {str(ex)[:80]}", file=sys.stderr)
        return []
    out = []
    for t in j.get("Table") or []:
        url = (t.get("PDFDownload") or "").replace("\\", "")  # 2023 RIL row carried a stray '\b'
        yr = str(t.get("Year") or "")
        if not url.lower().endswith(".pdf") or not re.match(r"^\d{4}$", yr):
            continue
        out.append(
            {
                "kind": "ar",
                "fy": int(yr),
                "date": f"{yr}-03-31",
                "url": url,
                "att": url.rsplit("/", 1)[-1],
                "title": f"Annual Report FY{yr[2:]}",
                "size": 0,
            }
        )
    return out


BASES = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
)


def _valid_pdf(raw):
    return raw is not None and len(raw) > 2000 and raw[:5] == b"%PDF-"


def fetch(doc, sym="_"):
    """Download one document into the cache; returns the local path or None. Validates the bytes."""
    att = doc["att"]
    d = os.path.join(CACHE, sym)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, att)
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return path
    urls = [doc["url"]] if doc.get("url") else []
    urls += [b + att for b in BASES]
    # AnnPdfOpen resolves the third (pre-2018 CorpAttachment/<Y>/<M>) base with a 302
    urls.append("https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=" + att)
    for u in urls:
        try:
            raw = _get(u, timeout=180, binary=True)
        except urllib.error.HTTPError as ex:
            if ex.code not in (404, 400):
                print("  fetch %s HTTP %d" % (att, ex.code), file=sys.stderr)
            continue
        except Exception as ex:
            print(f"  fetch {att} ERR {str(ex)[:80]}", file=sys.stderr)
            continue
        if _valid_pdf(raw):
            with open(path, "wb") as fh:
                fh.write(raw)
            return path
    return None


def page_texts(path, max_pages=None):
    """[(page_no_1based, text)] via PyMuPDF. Empty text = scanned page (needs vision)."""
    import fitz

    doc = fitz.open(path)
    out = []
    for i, pg in enumerate(doc):
        if max_pages and i >= max_pages:
            break
        out.append((i + 1, pg.get_text("text")))
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("syms", nargs="+")
    ap.add_argument("--since", default="2025-06-01")
    ap.add_argument("--kinds", default="ip,pr,res,ar")
    ap.add_argument("--fetch", action="store_true", help="download the listed documents into the cache")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    for s in a.syms:
        docs = list_docs(s, since=a.since, kinds=tuple(a.kinds.split(",")), verbose=a.v)
        print("%s (BSE %s): %d docs" % (s, scripcode(s), len(docs)))
        for d in docs:
            line = "  %s %-4s %7.1fMB %s  %s" % (d["date"], d["kind"], d["size"] / 1e6, d["att"], d["title"][:60])
            if a.fetch:
                p = fetch(d, s)
                line += "  -> %s" % (os.path.basename(p) if p else "FAILED")
            print(line)
