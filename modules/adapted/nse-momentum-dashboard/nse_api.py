from __future__ import annotations

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


"""
NSE corporate-data API client.

Endpoints wrapped (all need a cookie-warmed session + browser headers):
  /api/corporate-announcements        -> events, order wins, red flags
  /api/annual-reports                 -> annual report PDFs (1-5 yrs)
  /api/corporates-corporateActions    -> dividends, splits, bonuses, ex-dates
  /api/corporate-share-holdings-master-> promoter holding TIME SERIES
  /api/integrated-filing-results      -> quarterly results as XBRL (!)

The XBRL endpoint is the important one: it returns machine-readable *as
reported* financials straight from the company's filing — no HTML scraping,
no third-party interpretation, no staleness. That is a materially better
foundation than screener.in for anything you intend to trade.

Everything is cached to disk under cache/nse/ because these filings are
immutable once published.
"""


import datetime as dt
import hashlib
import json
import os
import re
import time

import requests

CACHE_ROOT = os.path.join("cache", "nse")
NSE_HOME = "https://www.nseindia.com"
BASE = "https://www.nseindia.com/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}

_session: requests.Session | None = None
_session_born: float = 0.0
SESSION_TTL = 600  # NSE cookies go stale; refresh every 10 min


def session() -> requests.Session:
    """Cookie-warmed session, auto-refreshed."""
    global _session, _session_born
    if _session is None or (time.time() - _session_born) > SESSION_TTL:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.get(NSE_HOME, timeout=15)
        # second hit: NSE sets its real cookies on the follow-up
        s.get(f"{NSE_HOME}/companies-listing/corporate-filings-announcements", timeout=15)
        _session, _session_born = s, time.time()
    return _session


def _cache_path(kind: str, symbol: str) -> str:
    d = os.path.join(CACHE_ROOT, kind)
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", symbol)
    return os.path.join(d, f"{safe}.json")


def _get_json(path: str, params: dict, kind: str, symbol: str, max_age_hours: float = 12) -> list | dict:
    cp = _cache_path(kind, symbol)
    if os.path.exists(cp):
        age = (time.time() - os.path.getmtime(cp)) / 3600
        if age < max_age_hours:
            with open(cp) as f:
                return json.load(f)
    try:
        r = session().get(f"{BASE}/{path}", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        with open(cp, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        if os.path.exists(cp):
            with open(cp) as f:
                return json.load(f)
        print(f"[nse] {kind}/{symbol} failed: {e}")
        return [] if kind != "filings" else {}


# ---------------------------------------------------------------------------
# The five endpoints
# ---------------------------------------------------------------------------


def corporate_announcements(symbol: str) -> list[dict]:
    """Recent announcements. Fields: an_dt, desc, attchmntText, attchmntFile."""
    data = _get_json(
        "corporate-announcements",
        {"index": "equities", "symbol": symbol, "reqXbrl": "false"},
        "announcements",
        symbol,
        max_age_hours=6,
    )
    return data if isinstance(data, list) else data.get("data", [])


def annual_reports(symbol: str) -> list[dict]:
    """Annual report PDFs. Fields: fromYr, toYr, fileName."""
    data = _get_json(
        "annual-reports", {"index": "equities", "symbol": symbol}, "annual_reports", symbol, max_age_hours=24 * 7
    )
    return data.get("data", []) if isinstance(data, dict) else data


def corporate_actions(symbol: str) -> list[dict]:
    """Dividends/splits/bonuses. Fields: exDate, recDate, subject."""
    data = _get_json(
        "corporates-corporateActions", {"index": "equities", "symbol": symbol}, "corp_actions", symbol, max_age_hours=24
    )
    return data if isinstance(data, list) else data.get("data", [])


def shareholding_pattern(symbol: str) -> list[dict]:
    """Quarterly shareholding. Fields: date, pr_and_prgrp, public_val."""
    data = _get_json(
        "corporate-share-holdings-master",
        {"index": "equities", "symbol": symbol},
        "shareholding",
        symbol,
        max_age_hours=24 * 7,
    )
    return data if isinstance(data, list) else data.get("data", [])


def integrated_filings(symbol: str) -> list[dict]:
    """Quarterly results filings incl. XBRL URLs.
    Fields: qe_Date, consolidated, audited, xbrl, ixbrl."""
    data = _get_json(
        "integrated-filing-results", {"index": "equities", "symbol": symbol}, "filings", symbol, max_age_hours=6
    )
    return data.get("data", []) if isinstance(data, dict) else data


def legacy_quarterly_results(symbol: str) -> list[dict]:
    """Quarterly results from NSE's older reporting system (pre-dates
    integrated-filing-results), going back to ~2008 for long-listed
    companies — 'issuer' is NOT required despite appearing in some sample
    URLs (verified: dropping it returns the same result set).

    Each entry's XBRL file (URL pattern 'INDAS_<id>_...', distinct from
    'INTEGRATED_FILING_INDAS_...') contains ONLY that single quarter's
    figures — NOT a year-to-date context, unlike the newer system's Q4
    filings. NSE's own 'cumulative'/'relatingTo' metadata for these
    filings is unreliable (the same file gets tagged both "Cumulative"/
    "Annual" and "Non-cumulative"/"Fourth Quarter" depending on which
    query filter is used — verified by a full context-count audit of a
    real file: only quarter-length contexts exist, regardless of label).
    Use quarterly_summed_annual() to reconstruct genuine annual figures
    from four of these, rather than trusting either label.
    """
    data = _get_json(
        "corporates-financial-results",
        {"index": "equities", "symbol": symbol, "period": "Quarterly"},
        "legacy_quarterly",
        symbol,
        max_age_hours=24 * 7,
    )
    return data if isinstance(data, list) else []


def filing_taxonomy(symbol: str) -> str:
    """Which Ind-AS XBRL taxonomy variant NSE files this symbol under —
    determines which financial concepts exist in its filings and therefore
    which scoring rubric applies (see xbrl_parser.value_score / bank_score /
    nbfc_score / general_insurance_score / life_insurance_score). Grounded
    in the actual regulatory filing format (encoded in the XBRL filename
    itself), not a sector label that's inconsistently populated in
    announcement records.

    Returns: "banking", "nbfc" (also covers AMCs, per NSE's own filing
    classification), "general_insurance", "life_insurance", "general", or
    "unknown" if no financial filing is found at all (e.g. MCX, which has
    no filings via this endpoint at all — not a classification failure).
    """
    for f in integrated_filings(symbol):
        if f.get("type") != "Integrated Filing- Financials":
            continue
        url = f.get("xbrl") or ""
        if "INTEGRATED_FILING_BANKING_" in url:
            return "banking"
        if "INTEGRATED_FILING_NBFC_INDAS_" in url:
            return "nbfc"
        if "INTEGRATED_FILING_GI_" in url:
            return "general_insurance"
        if "INTEGRATED_FILING_LI_" in url:
            return "life_insurance"
        if "INTEGRATED_FILING_INDAS_" in url:
            return "general"
    return "unknown"


# ---------------------------------------------------------------------------
# File download (PDF / XBRL), content-addressed cache
# ---------------------------------------------------------------------------


def download(url: str, subdir: str = "files", max_mb: float = 40) -> str | None:
    """Download an nsearchives file, cached by URL hash. Returns local path."""
    if not url or "nsearchives" not in url or url.endswith("/null"):
        return None
    d = os.path.join(CACHE_ROOT, subdir)
    os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(url.split("?", maxsplit=1)[0])[1] or ".bin"
    path = os.path.join(d, hashlib.md5(url.encode()).hexdigest() + ext)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        r = session().get(url, timeout=90, stream=True)
        r.raise_for_status()
        size = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                size += len(chunk)
                if size > max_mb * 1e6:
                    f.close()
                    os.remove(path)
                    print(f"[nse] {url} exceeds {max_mb}MB, skipped")
                    return None
                f.write(chunk)
        return path
    except Exception as e:
        print(f"[nse] download failed {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Derived signals — the parts that are genuinely predictive
# ---------------------------------------------------------------------------


def _parse_nse_date(s: str) -> dt.date | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%B-%Y", "%d-%b-%Y %H:%M:%S.%f"):
        try:
            return dt.datetime.strptime(s.strip()[:20], fmt).date()
        except (ValueError, AttributeError):
            continue
    try:
        return dt.datetime.strptime(s.strip()[:11].upper(), "%d-%b-%Y").date()
    except Exception:
        return None


def promoter_trend(symbol: str) -> dict:
    """Promoter holding time series -> trend.

    This is one of the few genuinely forward-looking signals available for
    free: promoters increasing their stake with their own money, quarter
    after quarter, is a costly signal that's hard to fake. A steady *decline*
    is a real warning. (Insider-trading literature — Jeng, Metrick & Zeckhauser
    2003 — finds insider BUYING predicts returns; selling much less so.)
    """
    rows = shareholding_pattern(symbol)
    series = []
    for r in rows:
        d = _parse_nse_date(r.get("date", ""))
        try:
            v = float(r.get("pr_and_prgrp"))
        except (TypeError, ValueError):
            continue
        if d:
            series.append((d, v))
    series.sort()
    if len(series) < 2:
        return {
            "promoter_latest": None,
            "promoter_change_1y": None,
            "promoter_trend": "unknown",
            "promoter_series": series,
        }

    latest_d, latest_v = series[-1]
    year_ago = [v for d, v in series if (latest_d - d).days >= 300]
    change = latest_v - year_ago[-1] if year_ago else latest_v - series[0][1]

    if change > 0.5:
        trend = "increasing"
    elif change < -0.5:
        trend = "decreasing"
    else:
        trend = "stable"
    return {
        "promoter_latest": latest_v,
        "promoter_change_1y": round(change, 2),
        "promoter_trend": trend,
        "promoter_series": series,
    }


# Announcement categories that historically precede trouble or upside
RED_FLAG_PATTERNS = [
    (r"resignation.*(cfo|chief financial|auditor|managing director|md\b)", "senior exit (CFO/auditor/MD)"),
    (r"resignation of (statutory )?auditor", "auditor resignation"),
    (r"\bpledge|pledged shares|invocation", "promoter pledge activity"),
    (r"qualified opinion|adverse opinion|emphasis of matter", "audit qualification"),
    (r"\bsebi\b.*(order|penalty|show cause)|\bshow cause\b", "regulatory action"),
    (r"\bfraud|forensic audit|misappropriat", "fraud/forensic audit"),
    (r"insolvency|nclt|ibc\b|winding up", "insolvency proceedings"),
    (r"\bdefault\b.*(payment|interest|principal)", "payment default"),
    (r"rating.*(downgrade|revised downward)", "rating downgrade"),
    (r"search|seizure|raid|income tax department", "search/seizure"),
]

CATALYST_PATTERNS = [
    (r"\border\b.*(win|receipt|bagged|secured)|letter of award|\bloa\b", "order win"),
    (r"\bcapex|new plant|capacity expansion|greenfield|brownfield", "capacity expansion"),
    (r"\bacquisition|acquire|merger|amalgamation", "M&A"),
    (r"buyback|buy-back", "buyback"),
    (r"rating.*(upgrade|revised upward)", "rating upgrade"),
    (r"\bpreferential (issue|allotment)|qip|fund rais", "fund raise"),
    (r"stake (increase|acquisition) by promoter|promoter.*acquisition", "promoter buying"),
]


def classify_announcements(symbol: str, days: int = 365) -> dict:
    """Scan recent announcements for red flags and catalysts.

    Deterministic pattern matching runs FIRST so the AI layer never has to
    be trusted with the safety-critical part — a missed auditor resignation
    because an LLM was creative is not an acceptable failure mode.
    """
    anns = corporate_announcements(symbol)
    cutoff = dt.date.today() - dt.timedelta(days=days)
    flags, catalysts, recent = [], [], []

    for a in anns:
        d = _parse_nse_date(a.get("an_dt", ""))
        if not d or d < cutoff:
            continue
        text = f"{a.get('desc', '')} {a.get('attchmntText', '')}".lower()
        recent.append(
            {
                "date": d.isoformat(),
                "desc": a.get("desc", ""),
                "text": (a.get("attchmntText") or "")[:300],
                "file": a.get("attchmntFile"),
            }
        )
        for pat, label in RED_FLAG_PATTERNS:
            if re.search(pat, text) and label not in [f["type"] for f in flags]:
                flags.append({"type": label, "date": d.isoformat(), "text": (a.get("attchmntText") or "")[:200]})
        for pat, label in CATALYST_PATTERNS:
            if re.search(pat, text) and label not in [c["type"] for c in catalysts]:
                catalysts.append({"type": label, "date": d.isoformat(), "text": (a.get("attchmntText") or "")[:200]})

    return {"red_flags": flags, "catalysts": catalysts, "recent_announcements": recent[:40], "count": len(recent)}


def upcoming_corporate_actions(symbol: str, days: int = 120) -> list[dict]:
    """Corporate actions with an ex-date in the near future.

    Matters for a momentum book: an ex-dividend gap is not a breakdown, and
    a bonus/split changes the price series. Don't let your stop fire on a
    ₹12 ex-dividend gap and call it a trend break.
    """
    out = []
    today = dt.date.today()
    for ca in corporate_actions(symbol):
        ex = _parse_nse_date(ca.get("exDate", ""))
        if ex and today - dt.timedelta(days=7) <= ex <= today + dt.timedelta(days=days):
            out.append({"ex_date": ex.isoformat(), "subject": ca.get("subject"), "record_date": ca.get("recDate")})
    return sorted(out, key=lambda x: x["ex_date"])


def latest_annual_report_pdf(symbol: str, n_years: int = 5) -> list[dict]:
    """The last n annual reports, newest first, with local paths lazily set."""
    reports = annual_reports(symbol)
    out = []
    for r in reports[:n_years]:
        out.append({"from": r.get("fromYr"), "to": r.get("toYr"), "url": r.get("fileName"), "path": None})
    return out


_QUARTERLY_RESULT_TEXT = re.compile(r"financial results for the (period|quarter|year)", re.IGNORECASE)


def latest_quarterly_result_filing(symbol: str) -> dict | None:
    """Most recent 'Outcome of Board Meeting' announcement carrying the
    quarter's financial-results PDF, identified via attchmntText.

    That PDF is a cover letter + financial statement tables + segment info +
    Notes + the auditor's actual Limited Review Report for the quarter — a
    20-page filing vs. a 200-400 page annual report, available the same
    evening results are announced rather than once a year. The headline
    numbers duplicate what quarterly XBRL already gives us; the Notes and
    Limited Review Report narrative do not.
    """
    anns = corporate_announcements(symbol)
    matches = [
        a
        for a in anns
        if a.get("desc") == "Outcome of Board Meeting"
        and _QUARTERLY_RESULT_TEXT.search(a.get("attchmntText") or "")
        and a.get("attchmntFile")
    ]
    if not matches:
        return None
    matches.sort(key=lambda a: _parse_nse_date(a.get("an_dt", "")) or dt.date.min, reverse=True)
    best = matches[0]
    return {"date": best.get("an_dt"), "url": best.get("attchmntFile"), "text": best.get("attchmntText")}


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "HCLTECH"
    print(f"=== {sym} ===")
    print("promoter:", promoter_trend(sym))
    cls = classify_announcements(sym)
    print("red flags:", cls["red_flags"])
    print("catalysts:", cls["catalysts"])
    print("upcoming CA:", upcoming_corporate_actions(sym))
    print("annual reports:", latest_annual_report_pdf(sym))
    print("filings:", [(f.get("qe_Date"), f.get("consolidated")) for f in integrated_filings(sym)][:4])
