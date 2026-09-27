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


"""Assemble a research dossier for one or more BSE scrips (the deep-research input for the ideas routine).

Usage: python3 scripts/ideas/dossier.py <scrip> [<scrip> ...] [--days 240] [--no-pdf]
Writes scripts/ideas/_cache/dossier/<scrip>/dossier.md (+ dossier.json, and extracted text of the key PDFs
when PyMuPDF is importable). Everything comes from public BSE endpoints; nothing is inferred.

Sections: header (industry, PE, EPS), last quarters of results (BSE detailed results API; values are reported
by the API in Rs million and shown here in Rs crore), shareholding filings (promoter % parsed from the BSE SHP page
when possible), corporate actions, announcements in the last N days (with attachment links), annual reports,
adjusted price statistics, listed peers in the same industry (from docs/search_index.json) with BSE PE where available.
"""
import argparse
import datetime
import html
import json
import os
import re
import statistics
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
OUT = os.path.join(bse.CACHE, "dossier")


def qid(y, m):
    return 81 + (y - 2014) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]


def header(scrip):
    try:
        return json.loads(
            bse._get(
                f"https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w?quotetype=EQ&scripcode={scrip}&seriesid="
            )
        )
    except Exception:
        return {}


def results(scrip, n_quarters=10):
    """Last quarters from Corp_detailedResult_Transpose_ng. Tries the .00 and .50 (half-year/annual) variants."""
    today = ist.today()
    y, m = today.year, ((today.month - 1) // 3) * 3
    if m == 0:
        y, m = y - 1, 12
    ids = []
    for k in range(n_quarters + 2):
        ids.append(qid(y, m))
        m -= 3
        if m == 0:
            y, m = y - 1, 12
    out, seen = [], set()
    for q in ids:
        for suf in ("00", "50"):
            try:
                d = json.loads(
                    bse._get(
                        f"https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd={scrip}&qtr={q}.{suf}",
                        sleep=0.35,
                    )
                )
            except Exception:
                continue
            rows = d.get("table1") or []
            f = {}
            for r in rows:
                k = (r.get("fld_desc") or "").strip()
                v = (r.get("Value") or "").strip()
                if k and v and k not in f:
                    f[k] = v
            if not f.get("Date End"):
                continue
            key = (f.get("Date Begin"), f.get("Date End"), f.get("Type"))
            if key in seen:
                continue
            seen.add(key)

            def num(*names):
                for nme in names:
                    for k, v in f.items():
                        if k.lower().startswith(nme.lower()):
                            try:
                                return round(float(v) / 10, 2)  # Rs million -> Rs crore
                            except Exception:
                                return None
                return None

            out.append(
                {
                    "qid": f"{q}.{suf}",
                    "type": f.get("Type"),
                    "begin": f.get("Date Begin"),
                    "end": f.get("Date End"),
                    "revenue_cr": num("Net Sales/Revenue From Operations", "Revenue From Operations", "Net Sales"),
                    "other_income_cr": num("Other Income"),
                    "total_income_cr": num("Total Income"),
                    "expenditure_cr": num("Expenditure"),
                    "pbt_cr": num("Profit before tax", "Profit/(Loss) before tax"),
                    "pat_cr": num("Net Profit/(Loss) for the period", "Net Profit", "Profit after tax"),
                    "eps": None,
                    "raw": f,
                }
            )
            for k, v in f.items():
                if "eps" in k.lower() or "earning" in k.lower():
                    try:
                        out[-1]["eps"] = float(v)
                        break
                    except Exception:
                        pass

    def endkey(r):
        try:
            return datetime.datetime.strptime(r["end"], "%d-%b-%y").date()
        except Exception:
            return datetime.date(1900, 1, 1)

    out.sort(key=endkey, reverse=True)
    return out


def shareholding(scrip):
    try:
        t = (
            json.loads(bse._get(f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode={scrip}")).get(
                "Table"
            )
            or []
        )
    except Exception:
        return []
    rows = []
    for e in t[:6]:
        rec = {
            "quarter": e.get("qtr"),
            "filed": e.get("filing_date_time"),
            "url": "https://www.bseindia.com" + (e.get("xbrlurl") or ""),
            "promoter_pct": None,
            "pledge_pct": None,
        }
        try:
            page = bse._get(rec["url"], sleep=0.3).decode("utf-8", "ignore")
            text = re.sub(r"<[^>]+>", " ", page)
            text = html.unescape(re.sub(r"\s+", " ", text))
            m = re.search(r"Promoter\s*(?:&|and)\s*Promoter Group.{0,400}?(\d{1,3}\.\d{2})", text, re.IGNORECASE)
            if m:
                rec["promoter_pct"] = float(m.group(1))
        except Exception:
            pass
        rows.append(rec)
    return rows


def announcements_for(scrip, days):
    d_to = ist.today()
    d_from = d_to - datetime.timedelta(days=days)
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate={}&strScrip={}"
        "&strSearch=P&strToDate={}&strType=C&subcategory=-1".format(
            d_from.strftime("%Y%m%d"), scrip, d_to.strftime("%Y%m%d")
        )
    )
    try:
        rows = json.loads(bse._get(url)).get("Table") or []
    except Exception:
        rows = []
    return [
        {
            "date": (r.get("NEWS_DT") or "")[:10],
            "subject": (r.get("NEWSSUB") or "").strip(),
            "headline": (r.get("HEADLINE") or "").strip()[:400],
            "category": r.get("CATEGORYNAME"),
            "sub": r.get("SUBCATNAME"),
            "pdf": bse.attachment_url(r),
        }
        for r in rows
    ]


def annual_reports(scrip):
    try:
        t = (
            json.loads(bse._get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={scrip}")).get(
                "Table"
            )
            or []
        )
    except Exception:
        return []
    out = []
    for r in t[:4]:
        u = r.get("PDFDownload") or r.get("pdfurl") or ""
        out.append(
            {
                "year": r.get("Year") or r.get("year"),
                "url": u if u.startswith("http") else ("https://www.bseindia.com" + u if u else ""),
            }
        )
    return out


def price_stats(scrip):
    rows, events = bse.adjusted_history(scrip, d_from=ist.today() - datetime.timedelta(days=400))
    if not rows:
        return {}, []
    last = rows[-1]

    def ago(days):
        d = last["date"] - datetime.timedelta(days=days)
        prior = [r for r in rows if r["date"] <= d]
        return prior[-1]["close"] if prior else None

    y1 = [r for r in rows if r["date"] >= last["date"] - datetime.timedelta(days=365)]
    turn = [r["close"] * r["volume"] for r in y1[-60:]]
    st = {
        "last_date": last["date"].isoformat(),
        "last_close": round(last["close"], 2),
        "high_52w": round(max(r["close"] for r in y1), 2),
        "low_52w": round(min(r["close"] for r in y1), 2),
        "ret_1m": None,
        "ret_3m": None,
        "ret_6m": None,
        "ret_1y": None,
        "med_turnover_60d_lakh": round(statistics.median(turn) / 1e5, 1) if turn else None,
    }
    for k, days in (("ret_1m", 30), ("ret_3m", 91), ("ret_6m", 182), ("ret_1y", 365)):
        p = ago(days)
        if p:
            st[k] = round((last["close"] / p - 1) * 100, 1)
    return st, [f"{ex.isoformat()} x{f:g} {lab}" for ex, f, lab in events]


def peers(scrip, hdr):
    """Same-industry names from docs/search_index.json (industry index) with mcap; BSE PE looked up for BSE-listed ones."""
    try:
        si = json.load(open(os.path.join(DOCS, "search_index.json")))
    except Exception:
        return []
    master = {str(x["SCRIP_CD"]): x for x in bse.scrip_master()}
    me = master.get(str(scrip), {})
    my_id = (me.get("scrip_id") or "").strip()
    by_sym = {r[0]: r for r in si["s"]}
    row = by_sym.get(my_id)
    if not row:
        return []
    ind = row[4]
    same = [r for r in si["s"] if r[4] == ind and r[2] == 1 and r[0] != my_id and r[3] >= 100]
    same.sort(key=lambda r: abs((r[3] or 0) - (row[3] or 0)))
    out = []
    id2scrip = {(x.get("scrip_id") or "").strip(): str(x["SCRIP_CD"]) for x in master.values()}
    for r in same[:8]:
        pe = None
        sc = id2scrip.get(r[0])
        if sc and len(out) < 6:
            h = header(sc)
            try:
                pe = float(h.get("PE")) if h.get("PE") not in (None, "", "-") else None
            except Exception:
                pe = None
        out.append({"symbol": r[0], "name": r[1], "mcap": r[3], "pe": pe, "scrip": sc})
    return out


# Which filings are worth the six extraction slots, best class first. Ranked rather than taken in
# date order because the feed is mostly compliance noise: Modison's six most recent *matching*
# filings on 2026-09-22 were two newspaper publications, a board-meeting intimation, a scrutinizer's
# report and a "weblink of annual report" letter, which crowded out the one result PDF that carried
# the numbers. Anything not matched here is skipped.
DOC_CLASSES = [
    r"investor\s*presentation|earnings\s*call|transcript|concall",
    r"financial\s+results|un-?audited.*results|audited.*results|outcome of board meeting",
    r"credit\s*rating",
    r"award[_ ]of[_ ]order|receipt[_ ]of[_ ]order|capex|expansion|commercial production|capacity|acquisition|agreement|letter of award",
    r"press\s*release|media\s*release|business update",
]
# Compliance filings that carry no research content, even when their titles contain a keyword above
# ("Board Meeting Intimation for Approval For Financial Results" is not a result).
DOC_SKIP = re.compile(
    r"newspaper publication|board meeting intimation|trading window|scrutinizer|"
    r"certificate under reg|shareholders communication|weblink|voting result|"
    r"record date|postal ballot|compliance",
    re.IGNORECASE,
)


def doc_rank(a):
    """Rank an announcement for PDF extraction: 0 = best, None = not worth a slot."""
    t = (a.get("subject") or "") + " " + (a.get("headline") or "")
    if DOC_SKIP.search(t):
        return None
    for i, pat in enumerate(DOC_CLASSES):
        if re.search(pat, t, re.IGNORECASE):
            return i
    return None


def extract_pdf(url, dst, max_pages=60):
    try:
        import fitz  # PyMuPDF
    except Exception:
        print("pdf: PyMuPDF not installed, no document text extracted (pip install pymupdf)")
        return None
    try:
        data = bse.get_attachment(url, timeout=120)  # follows BSE's AttachLive -> AttachHis move
        if not data.startswith(b"%PDF"):
            print(f"pdf: not a PDF, skipped {url}")
            return None
        doc = fitz.open(stream=data, filetype="pdf")
        txt = []
        for i, p in enumerate(doc):
            if i >= max_pages:
                txt.append(f"\n[... truncated at {max_pages} pages of {len(doc)}]")
                break
            txt.append(p.get_text())
        open(dst, "w").write("\n".join(txt))
        return dst
    except Exception as e:  # say WHY: a silent None here reads as "no matching filings"
        print(f"pdf: extract failed {url}: {e}")
        return None


def build(scrip, days, pdf=True):
    d = os.path.join(OUT, str(scrip))
    os.makedirs(d, exist_ok=True)
    uni = {r["scrip"]: r for r in json.load(open(os.path.join(DOCS, "ideas", "universe.json")))["rows"]}
    u = uni.get(str(scrip), {})
    hdr = header(scrip)
    res = results(scrip)
    shp = shareholding(scrip)
    acts = bse.corporate_actions(scrip)
    ann = announcements_for(scrip, days)
    ars = annual_reports(scrip)
    st, adj = price_stats(scrip)
    prs = peers(scrip, hdr)
    key_docs = []
    if pdf:
        want = [a for a in ann if a["pdf"] and doc_rank(a) is not None]
        want.sort(key=lambda a: a["date"], reverse=True)  # newest first...
        want.sort(key=doc_rank)  # ...then stable by class, best first
        for i, a in enumerate(want[:6]):
            p = extract_pdf(a["pdf"], os.path.join(d, f"doc{i + 1}.txt"))
            if p:
                key_docs.append({"file": os.path.basename(p), "subject": a["subject"], "url": a["pdf"]})
        # The annual report is the method's core document (MD&A, capacity, related-party notes,
        # auditor remarks) but it is filed as its own record, not as an announcement, so it used to
        # be listed and never extracted - every run had to fetch it by hand. Take the latest one,
        # with a page budget that reaches the notes at the back of a 250-page report.
        if ars:
            yr, url = ars[0].get("year"), ars[0].get("url")  # annual_reports() returns newest first
            if url:
                p = extract_pdf(url, os.path.join(d, "annual_report.txt"), max_pages=300)
                if p:
                    key_docs.append({"file": os.path.basename(p), "subject": f"Annual report {yr}", "url": url})
    dj = {
        "scrip": str(scrip),
        "universe": u,
        "header": {
            k: hdr.get(k)
            for k in (
                "SecurityId",
                "ISIN",
                "Industry",
                "Sector",
                "IGroup",
                "ISubGroup",
                "Group",
                "FaceVal",
                "EPS",
                "PE",
                "PB",
                "ROE",
                "ConEPS",
                "ConPE",
            )
        },
        "results": res,
        "shareholding": shp,
        "corporate_actions": [{"ex": e[0].isoformat(), "factor": e[1], "label": e[2]} for e in acts],
        "announcements": ann,
        "annual_reports": ars,
        "price": st,
        "price_adjustments": adj,
        "peers": prs,
        "key_docs": key_docs,
        "built": ist.stamp(),
    }
    json.dump(dj, open(os.path.join(d, "dossier.json"), "w"), indent=1, default=str)
    L = [
        f"# Dossier: {u.get('name') or hdr.get('SecurityId')} (BSE {scrip}{', NSE ' + u['nse'] if u.get('nse') else ''})",
        "",
        (
            f"Built {dj['built']}. Market cap ₹{u.get('mcap')} cr (BSE master). Group {u.get('group')}{' SME' if u.get('sme') else ''}. "
            f"Industry: {hdr.get('Industry')} / {hdr.get('Sector')} / {hdr.get('ISubGroup')}. BSE header EPS {hdr.get('EPS')}, PE {hdr.get('PE')}, PB {hdr.get('PB')}, ROE {hdr.get('ROE')}."
        ),
        "",
        "## Price (adjusted for bonus/split)",
        "",
    ]
    if st:
        L.append(
            f"Last close ₹{st['last_close']} ({st['last_date']}). 52-week high ₹{st['high_52w']}, low ₹{st['low_52w']}. Returns 1m {st['ret_1m']}%, 3m {st['ret_3m']}%, 6m {st['ret_6m']}%, 1y {st['ret_1y']}%. Median daily turnover (60d) ₹{st['med_turnover_60d_lakh']} lakh."
        )
    if adj:
        L.append("Adjustments applied: " + "; ".join(adj))
    L += [
        "",
        "## Results (BSE detailed results; ₹ crore, converted from the API's ₹ million)",
        "",
        "| Period | Type | Revenue | Other inc | Total inc | PBT | PAT | EPS |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res[:10]:
        L.append(
            f"| {r['begin']} to {r['end']} | {r['type']} | {r['revenue_cr']} | {r['other_income_cr']} | {r['total_income_cr']} | {r['pbt_cr']} | {r['pat_cr']} | {r['eps']} |"
        )
    L += ["", "## Shareholding filings", ""]
    for s in shp:
        L.append(
            f"- {s['quarter']} (filed {s['filed']}): promoter {s['promoter_pct'] if s['promoter_pct'] is not None else 'unknown, open the page'}% — {s['url']}"
        )
    L += ["", "## Corporate actions (bonus/split)", ""]
    L += [f"- {e[0]} x{e[1]:g} {e[2]}" for e in acts] or ["- none recorded"]
    L += ["", f"## Announcements, last {days} days ({len(ann)})", ""]
    for a in ann[:60]:
        L.append(
            f"- {a['date']} [{a['category']}/{a['sub']}] {a['subject'][:110]} — {a['headline'][:160]} {('— ' + a['pdf']) if a['pdf'] else ''}"
        )
    L += ["", "## Annual reports", ""] + [f"- {r['year']}: {r['url']}" for r in ars] or ["- none"]
    L += [
        "",
        "## Peers (same industry in the site index; BSE PE where available)",
        "",
        "| Peer | Mcap ₹cr | PE |",
        "|---|---|---|",
    ]
    L += [f"| {p['name']} ({p['symbol']}) | {p['mcap']} | {p['pe'] if p['pe'] is not None else 'n/a'} |" for p in prs]
    if key_docs:
        L += ["", "## Extracted documents (read these)", ""] + [
            f"- {k['file']}: {k['subject'][:100]} — {k['url']}" for k in key_docs
        ]
    else:
        L += [
            "",
            "## Documents",
            "",
            "- PDF text not extracted in this run (PyMuPDF not available or no matching filings); open the attachment links above.",
        ]
    open(os.path.join(d, "dossier.md"), "w").write("\n".join(L) + "\n")
    print(
        "dossier ->",
        os.path.join(d, "dossier.md"),
        "| results",
        len(res),
        "| announcements",
        len(ann),
        "| peers",
        len(prs),
        "| docs",
        len(key_docs),
    )
    return dj


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scrips", nargs="+")
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    for s in a.scrips:
        build(s, a.days, pdf=not a.no_pdf)
