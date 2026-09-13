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
"""INSIGHTS — per-stock operating KPIs read from the company's OWN presentations (runbook §137).

What it does
  1. Picks the documents worth reading for a symbol (kpi_docs.list_docs): every Investor
     Presentation, the press release filed on a results day, and the results packet only when a
     company files neither. Annual reports are a separate (--annual) pass.
  2. Extracts the text layer per page (PyMuPDF), scores pages for KPI content, and builds ONE
     prompt per document that asks a model for business/operating metrics WITH the page number,
     the row label and the value exactly as printed.
  3. Validates the answer deterministically before anything is written:
       • period label → (type, end-date) by OUR parser, and it must agree with the model's own
         period_end (disagreement = hold, never a write);
       • the value AS PRINTED must occur in that page's text (the anti-hallucination gate —
         a number the page does not contain is rejected outright; scanned pages hold);
       • YoY/QoQ deltas, targets and guidance are refused by rule.
  4. Merges into scripts/kpi_insights/<SYM>.json — one metric row per business quantity,
     yearly (`y`) and quarterly (`q`) cells keyed by period-end YYYYMMDD, newest document wins,
     provenance per cell [attachment, page, label, as_printed]. build_stock_fin.py bakes the
     file into docs/fin/<SLUG>.json and stock.html renders the Insights card.

Backends
  --backend packet   write the prompt+text to a packet file for a Claude Code session/routine to
                     read and answer (answer JSON goes through --ingest). Used for pilots and as the
                     second reader.
  --backend gemini   Google AI Studio free tier (GEMINI_API_KEY; gemini_vision.py's pacing/quota).
                     The CI walker uses this.
Nothing here ever infers a value: no derivation, no carry-forward, no "probably unchanged".
"""
import argparse
import calendar
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kpi_docs  # noqa: E402

LEDGER_DIR = os.path.join(HERE, "kpi_insights")
PACKET_DIR = os.path.join(LEDGER_DIR, "_packets")
MAX_METRICS = 16
MAX_PAGES = 45  # pages sent per document (top-scored); raised so the business-profile /
MAX_CHARS = 90000  # multi-year-highlights slide is never dropped for a rich deck or annual report
SAVE_ANSWERS_DIR = None  # --save-answers DIR: gemini reads also persist their answer+meta here so a
#                          later --reapply-answers can RE-INGEST them onto the CURRENT ledger. The CI
#                          walker uses this to merge onto origin at commit time instead of overwriting
#                          the whole ledger dir (which silently reverted concurrent writers — §137).

KPI_WORDS = re.compile(
    r"operating metric|key metric|kpi|operational|highlights|volume|capacity|utili[sz]ation|"
    r"production|throughput|sales volume|realisation|realization|subscriber|customer|store|outlet|"
    r"branch|employee|headcount|order book|order inflow|backlog|aum|disbursement|advances|deposits|"
    r"casa|nim\b|gnpa|npa|cd ratio|market share|arpu|occupancy|passengers|fleet|footfall|"
    r"tonnage|mmt|mtpa|mw\b|gw\b|units|bcfe|mmscmd|room|beds|bookings|pre-?sales|collections|"
    r"area|sq\.? ?ft|network|towns|pin ?codes|attach rate|patents|dealers|distributors|"
    r"gross written|apе|persistency|premium|clients|active users|transactions|gmv|take rate",
    re.IGNORECASE,
)
PERIOD_WORDS = re.compile(
    r"\bQ[1-4]\s*FY|\b[1-4]Q\s*FY|\bFY\s*'?\d{2}|\bH[12]\s*FY|9M\s*FY|"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-' ]?\d{2}",
    re.IGNORECASE,
)
MON = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


# business-profile infographic tokens: "610+ Products", "~600 Customers", "55 Countries", "26 Patents",
# "5 Manufacturing Facilities", "2,937 branches", "13.2 Mn customers" — the "at a glance" slide screener
# mines and our page-scorer used to drop. Also the multi-year "10-year highlights / financial record" pages.
PROFILE_TOKENS = re.compile(
    r"\d[\d,]*\+?\s*(customers?|clients?|countr(?:y|ies)|patents?|manufacturing|facilit(?:y|ies)|plants?|"
    r"dealers?|distributors?|stores?|outlets?|branches?|products?|markets?|cities|towns|subscribers?|"
    r"employees?|scientists?|msf|units|beds|rooms|warehouses?|touchpoints?)",
    re.IGNORECASE,
)
PROFILE_MARKERS = re.compile(
    r"since inception|at a glance|company overview|business overview|our (?:reach|footprint|presence|journey)|"
    r"key highlights|10[- ]?year|ten[- ]?year|five[- ]?year|5[- ]?year|decade|financial highlights|"
    r"performance (?:highlights|record|trends)|historical (?:financials|performance)|milestones",
    re.IGNORECASE,
)


def score_page(text):
    nums = len(re.findall(r"\d[\d,]*\.?\d*", text))
    if nums < 6:
        return 0
    s = nums * 0.4 + 6 * len(KPI_WORDS.findall(text)) + 10 * min(len(PERIOD_WORDS.findall(text)), 6)
    # business-profile & multi-year-highlights boost — these pages carry the rows screener shows and more
    s += 8 * min(len(PROFILE_TOKENS.findall(text)), 8)
    if PROFILE_MARKERS.search(text):
        s += 40
    if re.search(r"disclaimer|safe harbour|forward.looking statements|cautionary", text, re.IGNORECASE):
        s *= 0.2
    return s


def select_pages(pages):
    """Top-scored pages, in document order, within the text budget."""
    scored = [(score_page(t), i, p, t) for i, (p, t) in enumerate(pages)]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(reverse=True)
    keep, chars = [], 0
    for _s, _i, p, t in scored:
        if len(keep) >= MAX_PAGES or chars + len(t) > MAX_CHARS:
            break
        keep.append((p, t))
        chars += len(t)
    keep.sort()
    return keep


# ------------------------------------------------------------------ document selection
def select_docs(sym, since, kinds=("ip", "pr", "res", "ar")):
    """Documents worth reading, newest first. Filings are clustered around each results day
    (-1..+3 days of a `res` filing): the Investor Presentation is the primary carrier and supersedes
    the press releases of that day; with no deck, every press release of the cluster is read (they
    are small); with neither, the results packet itself (many companies bundle the release inside).
    A deck filed outside any results window (an investor day, an AGM deck) is always read."""
    docs = kpi_docs.list_docs(sym, since=since, kinds=tuple(set(kinds) | {"res"}))
    res_dates = sorted({d["date"] for d in docs if d["kind"] == "res"})

    def cluster_of(date):
        d0 = dt.date.fromisoformat(date)
        for r in res_dates:
            if -1 <= (d0 - dt.date.fromisoformat(r)).days <= 3:
                return r
        return None

    clusters = {}
    loose = []
    for d in docs:
        c = cluster_of(d["date"])
        if c is None:
            loose.append(d)
        else:
            clusters.setdefault(c, []).append(d)
    # loose (non-results-clustered) docs: investor decks AND annual reports. Annual reports carry the
    # 10+ year business-profile record (customers, countries, patents, capacity by year) that screener
    # mines and quarterly decks never print — they are the depth this card was missing.
    chosen = [d for d in loose if d["kind"] in ("ip", "ar") and d["kind"] in kinds]
    for c, ds in clusters.items():
        ips = [d for d in ds if d["kind"] == "ip"]
        prs = [d for d in ds if d["kind"] == "pr"]
        rss = [d for d in ds if d["kind"] == "res"]
        if ips and "ip" in kinds:
            chosen += ips
        elif prs and "pr" in kinds:
            chosen += prs
        elif rss and "res" in kinds:
            chosen += rss[:1]
    # identical re-filings (same size, same day) — keep one
    seen, out = set(), []
    for d in sorted(chosen, key=lambda x: (x["date"], x["kind"], x["att"])):
        key = (d["date"], d["kind"], d["size"])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# ------------------------------------------------------------------ periods
def _fy_end(fy, fy_end_month):
    return dt.date(fy, fy_end_month, calendar.monthrange(fy, fy_end_month)[1])


def _q_end(fy, n, fy_end_month):
    """End date of quarter n (1-4) of fiscal year `fy` (the calendar year in which the FY ends)."""
    m = fy_end_month - (4 - n) * 3
    y = fy
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def _yy(s):
    v = int(s)
    return v if v > 100 else (2000 + v if v < 70 else 1900 + v)


def parse_period(label, fy_end_month=3):
    """Printed period label → ('q'|'y'|None, 'YYYYMMDD'|None). None = not a quarter/FY we store."""
    s = str(label or "").strip().replace("’", "'").replace("–", "-")
    low = s.lower()
    low = re.sub(r"(?<![a-z])f\s?'?(\d{2})\b", r"fy\1", low)  # Mahindra's "F27" / "Q1 F27" / "Q1F25" = FY27
    low = re.sub(r"\bq\s*([1-4])\s*(\d{2})-(\d{2})\b", r"q\1 fy\3", low)  # Coal India's "Q1 26-27" = Q1 FY27
    SEP = r"[\s,\-–/]*"  # "Q2, FY 26", "Q1-FY27", "Q4/FY26" all mean the same
    m = re.search(
        r"\bq\s*([1-4])" + SEP + r"(?:of\s*)?(?:fy\s*'?\s*)?(\d{4})\s*-\s*(\d{2,4})\b", low
    )  # Q1 FY 2026-27 / Q1 2026-27 → FY27
    if m:
        return "q", _q_end(_yy(m.group(3)), int(m.group(1)), fy_end_month).strftime("%Y%m%d")
    m = re.search(r"\bq\s*([1-4])" + SEP + r"(?:of\s*)?fy\s*'?\s*(\d{4}|\d{2})\b", low) or re.search(
        r"\b([1-4])\s*q" + SEP + r"fy\s*'?\s*(\d{4}|\d{2})\b", low
    )
    if m:
        return "q", _q_end(_yy(m.group(2)), int(m.group(1)), fy_end_month).strftime("%Y%m%d")
    m = re.search(r"\bq\s*([1-4])\s*'?\s*(\d{4}|\d{2})\b", low)  # "Q1'27", "Q4 2026"
    if m:
        return "q", _q_end(_yy(m.group(2)), int(m.group(1)), fy_end_month).strftime("%Y%m%d")
    if re.search(r"\b(h[12]|1h|2h|9m|ytd|ttm|ltm)\b", low):
        return None, None
    m = re.search(r"\bfy\s*'?\s*(\d{4})\s*-\s*(\d{2,4})\b", low)  # FY2025-26 → FY26
    if m:
        return "y", _fy_end(_yy(m.group(2)) if len(m.group(2)) == 2 else int(m.group(2)), fy_end_month).strftime(
            "%Y%m%d"
        )
    m = re.search(r"\bfy\s*'?\s*(\d{2})\s*-\s*(\d{2})\b", low)  # FY 25-26 → FY26
    if m:
        return "y", _fy_end(_yy(m.group(2)), fy_end_month).strftime("%Y%m%d")
    m = re.search(r"\bfy\s*'?\s*(\d{4}|\d{2})\b", low)
    if m:
        return "y", _fy_end(_yy(m.group(1)), fy_end_month).strftime("%Y%m%d")
    m = re.search(r"\b(\d{4})\s*-\s*(\d{2})\b", low)  # 2025-26
    if m and abs(int(m.group(1)) % 100 + 1 - int(m.group(2))) == 0:
        return "y", _fy_end(int(m.group(1)) + 1, fy_end_month).strftime("%Y%m%d")
    # month-year: "Jun-26", "June 2026", "30 Jun 2026", "30.06.2026", "June 30, 2026"
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", low)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            end = calendar.monthrange(y, mo)[1]
            if d == end and (mo - fy_end_month) % 3 == 0:
                return "q", dt.date(y, mo, d).strftime("%Y%m%d")
            return None, None
    # "30th June, 2025" / "31st Mar, 2026" / "June 30, 2026" / "Jun-26" / "Mar’26"
    m = re.search(r"\b\d{1,2}(?:st|nd|rd|th)?[-\s]*([a-z]{3})[a-z]*\.?[-\s',]*(\d{4}|\d{2})\b", low) or re.search(
        r"\b([a-z]{3})[a-z]*\.?[-\s',]*(?:\d{1,2}(?:st|nd|rd|th)?[-\s',]+)?(\d{4}|\d{2})\b", low
    )
    if m and m.group(1) in MON:
        mo, y = MON[m.group(1)], _yy(m.group(2))
        if (mo - fy_end_month) % 3 == 0:
            return "q", dt.date(y, mo, calendar.monthrange(y, mo)[1]).strftime("%Y%m%d")
        return None, None
    m = re.search(r"\bcy\s*'?(\d{4}|\d{2})\b", low)
    if m and fy_end_month == 12:
        return "y", _fy_end(_yy(m.group(1)), 12).strftime("%Y%m%d")
    return None, None


# ------------------------------------------------------------------ prompt
PROMPT = """You are reading pages from a document that {company} ({sym}, an Indian listed company) filed with the stock exchange: "{title}", dated {date}. Page text is given below, one page at a time, marked "=== PAGE n ===". Text was extracted from the PDF, so a table or chart may appear as a run of numbers followed by a run of period labels — pair them carefully and in order.

TASK: list the company's BUSINESS / OPERATING metrics that this document reports with a numeric value for a stated period — the kind of numbers an investor tracks to understand the business, for example: sales volumes, production, capacity and utilisation, realisation per unit, stores/outlets/branches, subscribers/customers/users, ARPU, order book/inflow, AUM, disbursements, deposits/advances/CASA/NIM/GNPA/NNPA/CD ratio for lenders, market share, occupancy, passengers, fleet, area (sq ft), headcount, patents, attach rates, gross written premium/persistency for insurers. Company-level P&L lines (revenue, EBITDA, PAT, EPS, margins, tax, cash flow, debt, market cap, share price) are NOT wanted — they are shown elsewhere. Segment-level VOLUMES are wanted; segment revenue/EBITDA are not.

RULES (each one is checked mechanically — a violation makes the whole metric worthless):
1. Only numbers PRINTED on a page. Never compute, convert, derive, extrapolate or carry a value forward. If the page prints "~285 Mn", as_printed is "285" and value is 285.
2. `as_printed` must be the number token exactly as it appears in the page text (digits, commas, decimal point; no unit, no ~, no %, no currency sign). `value` is that same number as a plain number.
3. `period` is the period label AS PRINTED next to the value or in its column/axis header (e.g. "Q1 FY27", "FY26", "Jun-26", "Q4FY26", "31.03.2026"). Also give `period_end` as the last calendar day of that period (YYYY-MM-DD) and `period_type` = "Q" for a quarter or a quarter-end snapshot, "FY" for a full financial year or FY-end snapshot, "other" for H1/H2/9M/TTM/months. {fy_note}
4. Skip growth rates, YoY/QoQ changes, bps changes, targets, guidance, ranges and industry/market data. Keep ratios the company reports as its own KPI (NIM %, GNPA %, CASA %, market share %, utilisation %, attach rate %). A mix share (export share of revenue, retail share of advances, a brand's share of revenue) is wanted ONLY when the document prints it as a named figure for at least two periods — never lift slices out of a single pie chart.
5. One metric = one business quantity in one unit, consistently across periods. Name it clearly and generically (e.g. "Total Customer Base", "Retail Store Count", "Gross NPA", "KG D6 Gas Production (RIL share)"), and put the unit in `unit` exactly as printed ("Mn", "₹/month", "BCFe", "MMT", "%", "INR Cr", "count", "sq ft Mn"). If a metric below in KNOWN METRICS is the same quantity, reuse that exact name and unit.
6. Prefer the value from a TABLE over the same value in a headline or bullet; do not list the same (metric, period) twice. Prefer metrics with several periods in this document. At most {max_metrics} metrics; most business-relevant first.
7. `page` is the PAGE n marker the value came from; `label` is the row/axis label as printed there. If a page prints a KPI with NO period next to it and the document reports one period (see its title/date), use that reporting period and end the label with " (doc period)".
7b. Give each metric a `kind`: "level" = a count, balance, capacity or ratio AS AT a date (stores, subscribers, employees, deposits, GNPA %, market share) — its Q4 value is the FY-end value; "flow" = a total or average OVER the period (production, volumes sold, disbursements, ARPU, net additions) — its Q4 value is NOT the FY value.
8. If these pages are not about {company}, or contain no such metrics, return an empty metrics list and say why in `note`.

KNOWN METRICS for this company (reuse names/units where the quantity matches):
{known}

Return ONLY JSON of this shape:
{{"company_matches": true, "doc_title": "<short title, e.g. Q1 FY27 Investor Presentation>", "note": "",
  "metrics": [{{"name": "...", "unit": "...", "kind": "level", "values": [{{"period": "Q1 FY27", "period_type": "Q", "period_end": "2026-06-30", "value": 533.3, "as_printed": "533.3", "page": 19, "label": "Total Customer base"}}]}}]}}

=== DOCUMENT TEXT ===
"""


def build_prompt(sym, company, doc, pages, known, fy_end_month):
    fy_note = (
        (f"This company's financial year ends in {calendar.month_name[fy_end_month]}.")
        if fy_end_month != 3
        else "Indian FY runs April–March: FY27 = Apr 2026–Mar 2027; Q1 FY27 ends 2026-06-30, Q4 FY26 ends 2026-03-31."
    )
    known_txt = "\n".join("- {} [{}]".format(m["name"], m["unit"]) for m in known) or "- (none yet)"
    head = PROMPT.format(
        company=company,
        sym=sym,
        title=doc.get("title") or doc["kind"],
        date=doc["date"],
        fy_note=fy_note,
        known=known_txt,
        max_metrics=MAX_METRICS,
    )
    body = "".join("=== PAGE %d ===\n%s\n" % (p, t.strip()) for p, t in pages)
    return head + body


# ------------------------------------------------------------------ ledger
def ledger_path(sym):
    return os.path.join(LEDGER_DIR, kpi_docs_slug(sym) + ".json")


def kpi_docs_slug(sym):
    return re.sub(r"[^A-Za-z0-9._-]", "_", sym)


def load_ledger(sym):
    p = ledger_path(sym)
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"sym": sym, "fy_end_month": 3, "docs": {}, "metrics": [], "held": []}


def save_ledger(L):
    os.makedirs(LEDGER_DIR, exist_ok=True)
    L["updated"] = dt.date.today().isoformat()
    for m in L["metrics"]:
        m["y"] = dict(sorted(m.get("y", {}).items()))
        m["q"] = dict(sorted(m.get("q", {}).items()))
    L["metrics"].sort(key=lambda m: (-(len(m["y"]) + len(m["q"])), m["name"]))
    with open(ledger_path(L["sym"]), "w", encoding="utf-8") as fh:
        json.dump(L, fh, ensure_ascii=False, indent=1)


def norm_name(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def norm_num(s):
    return re.sub(r"[^0-9.]", "", str(s or ""))


def find_metric(L, name, unit):
    n = norm_name(name)
    for m in L["metrics"]:
        if norm_name(m["name"]) == n or n in [norm_name(a) for a in m.get("aliases", [])]:
            return m
    return None


def to_float(v):
    try:
        f = float(str(v).replace(",", ""))
        return f if f == f else None
    except Exception:
        return None


def ingest(sym, doc, answer, pages_text, by="?", verbose=True):
    """Validate one document's answer and merge it. Returns (written, held, rejected) counts."""
    L = load_ledger(sym)
    fy_end_month = int(L.get("fy_end_month") or 3)
    att = doc["att"]
    page_map = {p: norm_num_text(t) for p, t in pages_text}
    L["docs"][att] = {
        "kind": doc["kind"],
        "date": doc["date"],
        "title": (answer.get("doc_title") or doc.get("title") or "")[:120],
        "read": dt.date.today().isoformat(),
        "by": by,
    }
    L["held"] = [h for h in L.get("held", []) if h.get("doc") != att]
    written = held = rejected = 0
    if not answer.get("company_matches", True):
        L["docs"][att]["note"] = "company_matches=false: " + str(answer.get("note", ""))[:200]
        save_ledger(L)
        return 0, 0, 0
    for met in answer.get("metrics") or []:
        name, unit = (met.get("name") or "").strip(), (met.get("unit") or "").strip()
        if not name:
            continue
        kind = "flow" if str(met.get("kind") or "").lower().startswith("f") else "level"
        m = find_metric(L, name, unit)
        if m is None:
            m = {"name": name[:80], "unit": unit[:24], "kind": kind, "y": {}, "q": {}, "src": {}}
            L["metrics"].append(m)
        elif norm_name(m["unit"]) != norm_name(unit) and unit:
            # same quantity, different printed unit → keep as a separate row rather than mixing units
            m2 = None
            for mm in L["metrics"]:
                if norm_name(mm["name"]) == norm_name(name) and norm_name(mm["unit"]) == norm_name(unit):
                    m2 = mm
            if m2 is None:
                m2 = {"name": name[:80], "unit": unit[:24], "kind": kind, "y": {}, "q": {}, "src": {}}
                L["metrics"].append(m2)
            m = m2
        for v in met.get("values") or []:
            val = to_float(v.get("value"))
            page = v.get("page")
            asp = str(v.get("as_printed") or "").strip()
            label = str(v.get("label") or "")[:80]
            per = str(v.get("period") or "")
            ptype, pend = parse_period(per, fy_end_month)
            why = None
            if re.search(
                r"target|guidance|projection|projected|outlook|ambition|aspiration|\bplan\b|planned|expected|estimate",
                (label + " " + name).lower(),
            ):
                why = f"target/guidance, not a reported figure (label {label[:40]!r})"  # CPPLUS p11 'Production Capacity Targets' slipped past the prompt
            elif val is None or not asp:
                why = "no value"
            elif ptype is None:
                why = f"period not q/y: {per!r}"
            else:
                # model's own period_end must agree with our parse (both derived from the printed label)
                me = str(v.get("period_end") or "").replace("-", "")
                if me and me != pend:
                    why = f"period_end disagrees: ours {pend} model {me} for {per!r}"
                elif not isinstance(page, int) or page not in page_map:
                    why = f"page {page!r} not in document"
                elif abs(to_float(asp) - val) > 1e-9 if to_float(asp) is not None else True:
                    why = f"as_printed {asp!r} != value {val!r}"
                elif norm_num(asp) not in page_map[page]:
                    if page_map[page].strip():
                        why = f"as_printed {asp!r} not on page {page}"
                    else:
                        why = f"page {page} has no text layer (scanned) — needs a vision read"
            if why:
                rec = {
                    "doc": att,
                    "metric": name,
                    "unit": unit,
                    "period": per,
                    "value": val,
                    "as_printed": asp,
                    "page": page,
                    "label": label,
                    "why": why,
                }
                if "scanned" in why or "period_end disagrees" in why:
                    L["held"].append(rec)
                    held += 1
                else:
                    rejected += 1
                if verbose:
                    print(
                        "   {} {} | {} {} = {} (p{}): {}".format(
                            "HOLD" if rec in L["held"] else "REJECT", name, per, unit, asp, page, why
                        )
                    )
                continue
            cell = m["y"] if ptype == "y" else m["q"]
            srckey = f"{ptype}:{pend}"
            old_src = m["src"].get(srckey)
            old_doc = L["docs"].get(old_src[0]) if old_src else None
            # Same value re-printed → keep the EARLIEST filing as the source (rewind then shows the
            # cell from the day the market first saw it). Different value → the NEWEST filing wins
            # (a restatement) and `restated` records what the older filing said.
            if old_doc and old_src[0] != att and pend in cell:
                older = old_doc.get("date", "") < doc["date"]
                if cell[pend] == val:
                    if older:
                        continue  # already sourced from an earlier filing
                    m["src"][srckey] = [att, page, label, asp]  # this filing is earlier: re-source
                    written += 1
                    continue
                if not older:
                    if verbose:
                        print(f"   keep newer {name} {pend}={cell[pend]} (older doc says {val})")
                    continue
                m.setdefault("restated", []).append([srckey, old_src[0], cell[pend], att, val])
            cell[pend] = val
            m["src"][srckey] = [att, page, label, asp]
            written += 1
    # drop empty metric shells
    L["metrics"] = [m for m in L["metrics"] if m["y"] or m["q"]]
    save_ledger(L)
    return written, held, rejected


def norm_num_text(t):
    """Page text with every number reduced to digits+dot so '1,10,396' and '110396' both match."""
    return " " + re.sub(r"(?<=\d),(?=\d)", "", t) + " "


# ------------------------------------------------------------------ backends
GEMINI = {"dead": False, "calls": 0, "prompt_tokens": 0, "last": 0.0}
GEMINI_MIN_GAP = float(os.environ.get("GEMINI_MIN_GAP", "6"))


def quota_dead():
    return GEMINI["dead"]


def gemini_answer(prompt):
    """One structured-JSON call to Gemini with quota handling measured for THIS job (2026-09-06):
    a 429 RESOURCE_EXHAUSTED came after a single ~20k-token prompt and gemini_vision._post()'s
    15-second retry declared the DAY dead. Google's 429 body carries `retryDelay` and the quota id
    (…PerMinute… / …PerDay…): honour the delay (up to 120 s, 6 attempts), log the body so the real
    limit is visible in the run log, and mark the day dead only when the id says PerDay."""
    import urllib.error
    import urllib.request

    key = os.environ.get("GEMINI_API_KEY")
    if not key or GEMINI["dead"]:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    schema = {
        "type": "OBJECT",
        "properties": {
            "company_matches": {"type": "BOOLEAN"},
            "doc_title": {"type": "STRING"},
            "note": {"type": "STRING"},
            "metrics": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING"},
                        "unit": {"type": "STRING"},
                        "kind": {"type": "STRING"},
                        "values": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "period": {"type": "STRING"},
                                    "period_type": {"type": "STRING"},
                                    "period_end": {"type": "STRING"},
                                    "value": {"type": "NUMBER"},
                                    "as_printed": {"type": "STRING"},
                                    "page": {"type": "INTEGER"},
                                    "label": {"type": "STRING"},
                                },
                                "required": [
                                    "period",
                                    "period_type",
                                    "period_end",
                                    "value",
                                    "as_printed",
                                    "page",
                                    "label",
                                ],
                            },
                        },
                    },
                    "required": ["name", "unit", "kind", "values"],
                },
            },
        },
        "required": ["company_matches", "doc_title", "note", "metrics"],
    }
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "response_mime_type": "application/json", "response_schema": schema},
        }
    ).encode()
    for attempt in range(6):
        gap = GEMINI_MIN_GAP - (time.time() - GEMINI["last"])
        if gap > 0:
            time.sleep(gap)
        GEMINI["last"] = time.time()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=240).read())
            GEMINI["calls"] += 1
            um = resp.get("usageMetadata") or {}
            GEMINI["prompt_tokens"] += int(um.get("promptTokenCount") or 0)
            txt = resp["candidates"][0]["content"]["parts"][0]["text"]
            print(
                "    gemini ok: %s prompt tokens (run total %s over %d calls)"
                % (um.get("promptTokenCount"), GEMINI["prompt_tokens"], GEMINI["calls"])
            )
            return json.loads(txt)
        except urllib.error.HTTPError as ex:
            try:
                body_txt = ex.read().decode("utf-8", "replace")
            except Exception:
                body_txt = ""
            flat = " ".join(body_txt.split())
            if ex.code == 429:
                m = re.search(r'"retryDelay":\s*"(\d+)s"', body_txt)
                delay = min(int(m.group(1)) + 3, 120) if m else 45
                print("    gemini 429 attempt %d/6 — wait %ds — %s" % (attempt + 1, delay, flat[:500]))
                if re.search(r"PerDay|per_day|daily", flat, re.IGNORECASE):
                    GEMINI["dead"] = True
                    print("    gemini DAILY quota exhausted — no more reads this run")
                    return None
                time.sleep(delay)
                continue
            if ex.code in (500, 502, 503, 504):
                print("    gemini HTTP %d attempt %d/6 — %s" % (ex.code, attempt + 1, flat[:200]))
                time.sleep(20 * (attempt + 1))
                continue
            print("    gemini HTTP %d — %s" % (ex.code, flat[:300]))
            return None
        except Exception as ex:
            print("    gemini err attempt %d/6: %s" % (attempt + 1, str(ex)[:160]))
            time.sleep(15)
    return None


_NAMES = None


def _name_index():
    """{sym: (name, rank)} from docs/search_index.json ({"s": [[sym, name, …], …]}, market-cap order)."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {}
        try:
            idx = json.load(open(os.path.join(HERE, "..", "docs", "search_index.json"), encoding="utf-8"))
            for i, r in enumerate(idx.get("s") or []):
                if isinstance(r, list) and r and r[0] not in _NAMES:
                    _NAMES[r[0]] = (str(r[1]) if len(r) > 1 and r[1] else r[0], i)
        except Exception:
            pass
    return _NAMES


def company_name(sym):
    return _name_index().get(sym, (sym, 0))[0]


def universe_symbols(kind="n500"):
    """Symbols to walk: the latest Nifty 500 snapshot (scripts/indices_history.json — the user's
    standing scope rule) plus scripts/kpi_insights/_extra_symbols.json (names asked for by hand),
    largest market cap first so the most-viewed pages fill first."""
    syms = []
    if kind in ("n500", "all"):
        h = json.load(open(os.path.join(HERE, "indices_history.json"), encoding="utf-8"))["Nifty 500"]
        syms += list(h[-1]["symbols"])
    extra = os.path.join(LEDGER_DIR, "_extra_symbols.json")
    if os.path.exists(extra):
        syms += [x for x in json.load(open(extra, encoding="utf-8")) if x not in syms]
    rank = _name_index()
    syms.sort(key=lambda x: rank.get(x, ("", 10**9))[1])
    return syms


def catalog(sym, since, kinds):
    """select_docs() with the BSE listing cached in the ledger: the first call walks the whole
    window back to `since` (~14 BSE windows for 2020→date); later calls re-list only the days
    since the last catalog and merge. Keeps the nightly BSE budget to ~1 call per symbol."""
    L = load_ledger(sym)
    cat = L.get("catalog") or []
    c_since, c_until = L.get("catalog_since"), L.get("catalog_until")
    today = dt.date.today().isoformat()
    if L.get("catalog_ver") != kpi_docs.CATALOG_VER:
        cat = []  # classification rules changed — re-list
    if cat and c_since and c_since <= since and c_until:
        fresh = select_docs(sym, (dt.date.fromisoformat(c_until) - dt.timedelta(days=7)).isoformat(), kinds)
        have = {d["att"] for d in cat}
        cat = cat + [d for d in fresh if d["att"] not in have]
    else:
        cat = select_docs(sym, since, kinds)
        c_since = since
    cat.sort(key=lambda d: d["date"], reverse=True)
    L = load_ledger(sym)
    L["catalog"], L["catalog_since"], L["catalog_until"] = cat, c_since, today
    L["catalog_ver"] = kpi_docs.CATALOG_VER
    save_ledger(L)
    return cat


def mark_checked(sym, note=None):
    L = load_ledger(sym)
    L["checked"] = dt.date.today().isoformat()
    if note:
        L["note"] = note
    save_ledger(L)


def walk(a, by):
    """Unattended pass (CI): read the newest unread documents of the symbols most in need.
    Never-checked symbols first, then the longest-unchecked; a symbol is re-listed on BSE at most
    once per --recheck-days. Stops at --max-docs reads, --max-syms listings, or a dead quota."""
    if not a.dry and not os.environ.get("GEMINI_API_KEY"):
        sys.exit("walk: GEMINI_API_KEY is not set — refusing to mark symbols checked without reading anything")
    syms = universe_symbols(a.universe)
    today = dt.date.today()

    def prio(x):
        if not os.path.exists(ledger_path(x)):
            return (0, "")
        L = load_ledger(x)
        return (1, L.get("checked") or L.get("updated") or "")

    syms.sort(key=prio)
    read = listed = 0
    for sym in syms:
        if read >= a.max_docs or listed >= a.max_syms:
            break
        if quota_dead():
            print("quota dead — stopping")
            break
        L = load_ledger(sym) if os.path.exists(ledger_path(sym)) else None
        chk = (L or {}).get("checked")
        if chk and (today - dt.date.fromisoformat(chk)).days < a.recheck_days:
            # recently listed — but keep reading while its cached catalog still holds unread filings
            # (the 2020→date backfill must not pause for --recheck-days after every pass)
            have_docs = (L or {}).get("docs", {})
            if not [d for d in (L or {}).get("catalog") or [] if d["att"] not in have_docs]:
                continue
        if not kpi_docs.scripcode(sym):
            mark_checked(sym, "no BSE scrip code in bse_scrips.json")
            continue
        docs = catalog(sym, a.since, tuple(a.kinds.split(",")))
        listed += 1
        have = set((L or {}).get("docs", {}).keys())
        pending = [d for d in docs if d["att"] not in have][: a.per_sym]
        print(
            "%s: %d documents, %d unread, reading %d"
            % (sym, len(docs), len([d for d in docs if d["att"] not in have]), len(pending))
        )
        n = run(sym, pending, "gemini", by, limit=max(0, a.max_docs - read), dry=a.dry) if pending else 0
        read += n
        if not a.dry:
            mark_checked(sym, None if docs else f"no presentations / press releases found on BSE since {a.since}")
    print("walk done: %d symbols listed, %d documents read" % (listed, read))


def known_metrics(L):
    return [{"name": m["name"], "unit": m["unit"]} for m in L["metrics"]][:40]


def run(sym, docs, backend, by, limit=None, dry=False):
    L = load_ledger(sym)
    fy_end_month = int(L.get("fy_end_month") or 3)
    comp = company_name(sym)
    done = 0
    for doc in docs:
        if limit and done >= limit:
            break
        if doc["att"] in L.get("docs", {}) and not getattr(run, "force", False):
            continue  # already read (packet mode too — a packet is for UNREAD filings)
        path = kpi_docs.fetch(doc, sym)
        if not path:
            print("  {} {}: download FAILED".format(sym, doc["att"]))
            continue
        pages = kpi_docs.page_texts(path)
        sel = select_pages(pages)
        if not sel:
            print(
                "  {} {} ({} {}): no text pages — scanned deck, vision route needed".format(
                    sym, doc["att"], doc["kind"], doc["date"]
                )
            )
            L = load_ledger(sym)
            L["docs"][doc["att"]] = {
                "kind": doc["kind"],
                "date": doc["date"],
                "title": doc.get("title", "")[:120],
                "read": dt.date.today().isoformat(),
                "by": by,
                "note": "no text layer",
            }
            save_ledger(L)
            continue
        L = load_ledger(sym)
        prompt = build_prompt(sym, comp, doc, sel, known_metrics(L), fy_end_month)
        if backend == "packet":
            os.makedirs(PACKET_DIR, exist_ok=True)
            pk = os.path.join(PACKET_DIR, "{}__{}.prompt.txt".format(kpi_docs_slug(sym), doc["att"][:8]))
            with open(pk, "w", encoding="utf-8") as fh:
                fh.write(prompt)
            meta = {"sym": sym, "doc": doc, "pages": [p for p, _ in sel], "path": path}
            with open(pk.replace(".prompt.txt", ".meta.json"), "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
            print("  packet %s (%s %s, %d pages, %d chars)" % (pk, doc["kind"], doc["date"], len(sel), len(prompt)))
            done += 1
            continue
        if dry:
            print("  would read %s %s %s (%d pages, %d chars)" % (sym, doc["kind"], doc["date"], len(sel), len(prompt)))
            done += 1
            continue
        ans = gemini_answer(prompt)  # retries 429/5xx internally (up to 6 attempts)
        if ans is None:
            if quota_dead():
                print(f"  {sym}: Gemini daily quota exhausted — stopping")
                break
            if not os.environ.get("GEMINI_API_KEY"):
                print(f"  {sym}: GEMINI_API_KEY missing")
                break
            print(
                "  {} {}: model returned nothing after retries — skipped (unread, retried next run)".format(
                    sym, doc["att"]
                )
            )
            continue
        if SAVE_ANSWERS_DIR:
            # persist the raw answer so the commit step can re-ingest it onto origin (§137 clobber fix)
            os.makedirs(SAVE_ANSWERS_DIR, exist_ok=True)
            stem = os.path.join(SAVE_ANSWERS_DIR, "{}__{}".format(kpi_docs_slug(sym), doc["att"][:8]))
            with open(stem + ".answer.json", "w", encoding="utf-8") as fh:
                json.dump(ans, fh, ensure_ascii=False)
            with open(stem + ".meta.json", "w", encoding="utf-8") as fh:
                json.dump({"sym": sym, "doc": doc, "pages": [pp for pp, _ in sel], "path": path, "by": by}, fh)
        w, h, r = ingest(sym, doc, ans, sel, by=by)
        print("  %s %s %s: written %d, held %d, rejected %d" % (sym, doc["kind"], doc["date"], w, h, r))
        done += 1
    return done


def ingest_answer(sym, att8, answer_path, by):
    meta_p = os.path.join(PACKET_DIR, f"{kpi_docs_slug(sym)}__{att8}.meta.json")
    meta = json.load(open(meta_p, encoding="utf-8"))
    pages = [pt for pt in kpi_docs.page_texts(meta["path"]) if pt[0] in set(meta["pages"])]
    ans = json.load(open(answer_path, encoding="utf-8"))
    w, h, r = ingest(sym, meta["doc"], ans, pages, by=by)
    print("%s %s: written %d, held %d, rejected %d" % (sym, att8, w, h, r))


def reapply_answers(dirpath):
    """Re-ingest every saved gemini answer in `dirpath` onto the CURRENT on-disk ledgers.
    The CI walker calls this AFTER `git reset --hard origin/main`, so gemini's cells MERGE onto
    whatever other writers landed (through the same validated ingest path) instead of the old
    whole-file overwrite that silently reverted them (§137). Re-reads each PDF from the cached
    path recorded in the meta; a missing PDF is skipped (the ledger simply keeps origin's cells,
    never a clobber). Idempotent: an answer already merged re-ingests to the same result."""
    metas = sorted(f for f in os.listdir(dirpath) if f.endswith(".meta.json")) if os.path.isdir(dirpath) else []
    n = tw = th = tr = 0
    for mf in metas:
        meta = json.load(open(os.path.join(dirpath, mf), encoding="utf-8"))
        af = os.path.join(dirpath, mf.replace(".meta.json", ".answer.json"))
        if not os.path.exists(af):
            continue
        ans = json.load(open(af, encoding="utf-8"))
        try:
            pages = [pt for pt in kpi_docs.page_texts(meta["path"]) if pt[0] in set(meta["pages"])]
        except Exception as ex:
            print(f"  reapply {mf}: page read FAILED ({str(ex)[:80]}) — skipped")
            continue
        w, h, r = ingest(meta["sym"], meta["doc"], ans, pages, by=meta.get("by", "gemini"), verbose=False)
        n += 1
        tw += w
        th += h
        tr += r
    print("reapply: %d answers re-ingested onto current ledgers — written %d, held %d, rejected %d" % (n, tw, th, tr))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("syms", nargs="*")
    ap.add_argument("--since", default="2020-01-01")
    ap.add_argument("--kinds", default="ip,pr,res,ar")
    ap.add_argument("--backend", default="gemini", choices=["gemini", "packet"])
    ap.add_argument("--by", default=None, help="reader tag stored in provenance")
    ap.add_argument("--limit", type=int, default=None, help="max documents per symbol this run")
    ap.add_argument("--list", action="store_true", help="only list the documents that would be read")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--walk", action="store_true", help="unattended pass over the universe (CI)")
    ap.add_argument("--universe", default="n500")
    ap.add_argument("--max-docs", type=int, default=500)
    ap.add_argument("--max-syms", type=int, default=200)
    ap.add_argument("--per-sym", type=int, default=4)
    ap.add_argument("--recheck-days", type=int, default=2)
    ap.add_argument("--ingest", nargs=3, metavar=("SYM", "ATT8", "ANSWER_JSON"))
    ap.add_argument("--show", metavar="SYM")
    ap.add_argument("--forget", nargs=2, metavar=("SYM", "ATT8"), help="drop a read document so it is read again")
    ap.add_argument(
        "--next",
        type=int,
        metavar="N",
        help="print the N symbols most in need of reading (priority order) with unread counts",
    )
    ap.add_argument(
        "--shard",
        metavar="K/N",
        help="with --next: only symbols whose roster index %% N == K, so N parallel routines read disjoint slices",
    )
    ap.add_argument("--force", action="store_true", help="re-emit packets even for documents already read")
    ap.add_argument("--report", action="store_true", help="one line per ledger: metrics, cells, docs, held")
    ap.add_argument(
        "--save-answers",
        metavar="DIR",
        help="gemini backend: also write each answer+meta to DIR for a later --reapply-answers (concurrency-safe commit)",
    )
    ap.add_argument(
        "--reapply-answers",
        metavar="DIR",
        help="re-ingest every saved answer in DIR onto the current on-disk ledgers (CI commit step, after reset --hard origin/main)",
    )
    a = ap.parse_args()
    if a.reapply_answers:
        reapply_answers(a.reapply_answers)
        return
    if a.ingest:
        ingest_answer(a.ingest[0], a.ingest[1], a.ingest[2], a.by or "claude-session")
        return
    if a.next:
        # BREADTH-FIRST priority: fewest filings already read first (never-started & thin stocks ahead
        # of already-deep megacaps), tie-broken by universe order (market cap). This spreads the deep
        # pass across the whole roster instead of exhausting the top few names' back-catalogue before
        # anyone else is touched. Ranking reads only the on-disk ledger (no BSE call); catalogs are
        # built lazily in that order until N stocks with unread filings are found.
        syms = universe_symbols(a.universe)
        rank = {s: i for i, s in enumerate(syms)}

        def reads_of(sym):
            if not os.path.exists(ledger_path(sym)):
                return 0
            L = load_ledger(sym) or {}
            return sum(1 for d in L.get("docs", {}).values() if d.get("read"))

        cand = [s for s in syms if kpi_docs.scripcode(s)]
        if a.shard:  # "K/N": disjoint slice of the roster for parallel routines
            k, n = (int(x) for x in a.shard.split("/"))
            cand = [s for s in cand if rank[s] % n == k]
        ranked = sorted(cand, key=lambda s: (reads_of(s), rank[s]))
        rows = []
        for sym in ranked:
            if len(rows) >= a.next:
                break
            L = load_ledger(sym) if os.path.exists(ledger_path(sym)) else None
            if L and L.get("catalog") and L.get("catalog_ver") == kpi_docs.CATALOG_VER:
                cat = L["catalog"]
            else:
                cat = catalog(sym, a.since, tuple(a.kinds.split(",")))
                L = load_ledger(sym)
            unread = [d for d in cat if d["att"] not in (L or {}).get("docs", {})]
            if unread:
                rows.append((sym, len(unread), len(cat), unread[0]["date"]))
        for sym, n, tot, newest in rows:
            print("%-12s unread %3d of %3d (newest %s)" % (sym, n, tot, newest))
        return
    if a.forget:
        L = load_ledger(a.forget[0])
        atts = [k for k in L["docs"] if k.startswith(a.forget[1])]
        for k in atts:
            del L["docs"][k]
        L["held"] = [h for h in L.get("held", []) if not h.get("doc", "").startswith(a.forget[1])]
        save_ledger(L)
        print("%s: forgot %d document(s) %s" % (a.forget[0], len(atts), atts))
        return
    if a.report:
        tot = {"syms": 0, "metrics": 0, "cells": 0, "docs": 0, "held": 0}
        for fn in sorted(os.listdir(LEDGER_DIR)) if os.path.isdir(LEDGER_DIR) else []:
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            L = json.load(open(os.path.join(LEDGER_DIR, fn), encoding="utf-8"))
            cells = sum(len(m.get("y", {})) + len(m.get("q", {})) for m in L.get("metrics", []))
            print(
                "%-14s metrics %2d  cells %4d  docs %2d  held %2d  checked %s %s"
                % (
                    L.get("sym", fn),
                    len(L.get("metrics", [])),
                    cells,
                    len(L.get("docs", {})),
                    len(L.get("held", [])),
                    L.get("checked") or "-",
                    ("· " + L["note"]) if L.get("note") else "",
                )
            )
            tot["syms"] += 1
            tot["metrics"] += len(L.get("metrics", []))
            tot["cells"] += cells
            tot["docs"] += len(L.get("docs", {}))
            tot["held"] += len(L.get("held", []))
        print("TOTAL", tot)
        return
    if a.show:
        L = load_ledger(a.show)
        for m in L["metrics"]:
            print("%-48s %-10s y=%s q=%s" % (m["name"][:48], m["unit"][:10], m["y"], m["q"]))
        print("held:", len(L.get("held", [])))
        return
    if a.save_answers:
        globals()["SAVE_ANSWERS_DIR"] = a.save_answers
    by = a.by or (
        "gemini:" + os.environ.get("GEMINI_MODEL", "gemini-3.6-flash") if a.backend == "gemini" else "claude-session"
    )
    if a.walk:
        walk(a, by)
        return
    run.force = a.force
    for sym in a.syms:
        docs = select_docs(sym, a.since, tuple(a.kinds.split(",")))
        print("%s: %d documents selected" % (sym, len(docs)))
        if a.list:
            for d in docs:
                print("  %s %-4s %6.1fMB %s %s" % (d["date"], d["kind"], d["size"] / 1e6, d["att"], d["title"][:50]))
            continue
        run(sym, docs, a.backend, by, limit=a.limit, dry=a.dry)


if __name__ == "__main__":
    main()
