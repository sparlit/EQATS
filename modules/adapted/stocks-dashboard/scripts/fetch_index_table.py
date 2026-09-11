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


#!/usr/bin/env python3
"""Build docs/indices.json — the live NSE-indices table for docs/indices.html.

WHAT THE PAGE SHOWS (per index): level, 1D/1W/1M/1Y %, PE, PB, dividend yield,
a 30-day sparkline, a 52-week-range position, PE/PB valuation percentile vs the
index's OWN history, and relative strength vs Nifty 50.

SOURCES (layered, each best-effort so a partial failure never blanks the page):
  1. liveindexsa.niftyindices.com/jsonfiles/LiveIndicesWatch.json  (CDN, NO bot
     wall — works everywhere incl. locally): every NSE index's level, 1D %,
     open/high/low, 52-week high/low. This is the ALWAYS-ON backbone.
  2. NSE /api/allIndices (cookie-primed via build_fundamentals; works in CI, 403s
     from many raw IPs): adds PE / PB / dividend yield and NSE's own perChange30d /
     perChange365d. When present these fill the PE/PB/DY columns and are the
     preferred 1M / 1Y numbers (available from day one, unlike our own window).
     ⚠️ Its perChange365d/perChange30d use 0 as a NO-BASE SENTINEL — see
     _fetch_nse_valuation() for the measured evidence and the suppression rule.

TWO FILES, like index_monthly.json's split of snapshot vs history:
  * docs/indices_hist.json  — SIDE file, NOT shipped to the browser. Rolling daily
    closes (DAILY_KEEP sessions, enough for a 1Y lookback once accrued) plus daily
    PE/PB/DY samples (PEPB_KEEP, for the valuation percentile). Grows organically
    from the first run — 1W fills after ~a week, 1M after ~a month, the PE
    percentile sharpens over weeks. Same "window builds up one evening at a time"
    property as the Deals / Monthly-Returns feeds (NSE's per-index daily archive is
    bot-walled, so we can't backfill it).
  * docs/indices.json — the page payload. Slim & fully pre-computed: every derived
    number (changes, percentiles, 52w position, RS, sparkline) is baked here so the
    page just renders. No history is shipped, so first load stays small.

Safety: if the primary (liveindexsa) fetch fails, BOTH files are left untouched
(exit 0) so the page keeps yesterday's data; guard_feed.py separately blocks a
shrunken commit. Target session date comes from the feed's own timeVal, never the
wall clock, so a morning catch-up run never mislabels a session.

stdlib only + build_fundamentals (shared NSE cookie-primed opener). Runbook §35.
"""
import contextlib
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import build_fundamentals as B  # shared NSE cookie jar / opener / UA
except Exception:
    B = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "indices.json")
HIST = os.path.join(ROOT, "docs", "indices_hist.json")
MEMBERS = os.path.join(ROOT, "scripts", "indices_history.json")

LIVE_URL = "https://liveindexsa.niftyindices.com/jsonfiles/LiveIndicesWatch.json"
DAILY_KEEP = 260  # sessions kept (~1 trading year — enough for the 1Y column once accrued)
PEPB_KEEP = 750  # PE/PB/DY samples kept per index (~3y) for the valuation percentile
SPARK_N = 30  # sparkline length (trading sessions)

MONTHS = {
    m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
}

# ---- Display names: the live watch spells several indices in a terse ALL-CAPS
# form. Map the ones that don't title-case cleanly; everything else is prettified
# by _label() below. Keys are the raw indexName from LiveIndicesWatch.
LABELS = {
    "NIFTY SMLCAP 100": "Nifty Smallcap 100",
    "NIFTY SMLCAP 250": "Nifty Smallcap 250",
    "NIFTY MICROCAP250": "Nifty Microcap 250",
    "NIFTY PVT BANK": "Nifty Private Bank",
    "NIFTY FIN SERVICE": "Nifty Financial Services",
    "NIFTY FINSRV25 50": "Nifty Fin Services 25/50",
    "NIFTY FINSEREXBNK": "Nifty Fin Services Ex-Bank",
    "NIFTY OIL AND GAS": "Nifty Oil & Gas",
    "NIFTY CONSR DURBL": "Nifty Consumer Durables",
    "NIFTY TOTAL MKT": "Nifty Total Market",
    "NIFTY LARGEMID250": "Nifty LargeMidcap 250",
    "NIFTY MIDSMALLCAP 400": "Nifty MidSmallcap 400",
    "NIFTY MID SELECT": "Nifty Midcap Select",
    "NIFTY SERV SECTOR": "Nifty Service Sector",
    "NIFTY NONCYC CONS": "Nifty Non-Cyclical Consumer",
    "NIFTY TRANS LOGIS": "Nifty Transport & Logistics",
    "NIFTY CONSUMPTION": "Nifty India Consumption",
    "NIFTY IND DEFENCE": "Nifty India Defence",
    "NIFTY IND DIGITAL": "Nifty India Digital",
    "NIFTY IND TOURISM": "Nifty India Tourism",
    "NIFTY INDIA MFG": "Nifty India Manufacturing",
    "NIFTY MS IT TELCM": "Nifty MidSmall IT & Telecom",
    "NIFTY MS FIN SERV": "Nifty MidSmall Financial Services",
    "NIFTY MS IND CONS": "Nifty MidSmall Ind Consumption",
    "NIFTY MIDSML HLTH": "Nifty MidSmall Healthcare",
    "NIFTY NEW CONSUMP": "Nifty New Consumption",
    "NIFTY COREHOUSING": "Nifty Core Housing",
    "NIFTY CORP MAATR": "Nifty Corporate MAATR",
    "NIFTY CAPITAL MKT": "Nifty Capital Markets",
    "NIFTY DIV OPPS 50": "Nifty Dividend Opportunities 50",
    "NIFTY GROWSECT 15": "Nifty Growth Sectors 15",
    "NIFTY100 LIQ 15": "Nifty100 Liquid 15",
    "NIFTY100 LOWVOL30": "Nifty100 Low Volatility 30",
    "NIFTY100 QUALTY30": "Nifty100 Quality 30",
    "NIFTY100ESGSECLDR": "Nifty100 ESG Sector Leaders",
    "NIFTY200 ALPHA 30": "Nifty200 Alpha 30",
    "NIFTY200 QUALTY30": "Nifty200 Quality 30",
    "NIFTY200 VALUE 30": "Nifty200 Value 30",
    "NIFTY200MOMENTM30": "Nifty200 Momentum 30",
    "NIFTY50 EQL WGT": "Nifty50 Equal Weight",
    "NIFTY50 VALUE 20": "Nifty50 Value 20",
    "NIFTY500 EW": "Nifty500 Equal Weight",
    "NIFTY500MOMENTM50": "Nifty500 Momentum 50",
    "NIFTYM150MOMNTM50": "Nifty Midcap150 Momentum 50",
    "NIFTYSML250MQ 100": "Nifty Smallcap250 MomentumQuality 100",
    "NIFTY MID LIQ 15": "Nifty Midcap Liquid 15",
    "NIFTY QLTY LV 30": "Nifty Quality Low-Vol 30",
    "NIFTY M150 QLTY50": "Nifty Midcap150 Quality 50",
    "NIFTY LOW VOL 50": "Nifty Low Volatility 50",
    "NIFTY HIGHBETA 50": "Nifty High Beta 50",
    "NIFTY ALPHALOWVOL": "Nifty Alpha Low-Vol 30",
    "NIFTY100 ALPHA 30": "Nifty100 Alpha 30",
    "NIFTY100 ENH ESG": "Nifty100 Enhanced ESG",
    "NIFTY100 EQL WGT": "Nifty100 Equal Weight",
    "NIFTY100 ESG": "Nifty100 ESG",
    "NIFTY500 QLTY50": "Nifty500 Quality 50",
    "NIFTY500 VALUE 50": "Nifty500 Value 50",
    "NIFTY500 LOWVOL50": "Nifty500 Low Volatility 50",
    "NIFTY SML250 Q50": "Nifty Smallcap250 Quality 50",
    "NIFTY MULTI MQ 50": "Nifty Multi MomentumQuality 50",
    "NIFTY AQL 30": "Nifty Alpha Quality 30",
    "NIFTY AQLV 30": "Nifty Alpha Quality Low-Vol 30",
    "NIFTY MNC": "Nifty MNC",
    "NIFTY PSE": "Nifty PSE",
    "NIFTY CPSE": "Nifty CPSE",
    "NIFTY PSU BANK": "Nifty PSU Bank",
    "NIFTY IT": "Nifty IT",
    "NIFTY EV": "Nifty EV & New Age Auto",
    "NIFTY IPO": "Nifty IPO",
    "NIFTY REITS & REALTY": "Nifty REITs & Realty",
    "NIFTY INDIA RAILWAYS PSU": "Nifty India Railways PSU",
    "NIFTY CONGLOMERATE 50": "Nifty Conglomerate 50",
    "NIFTY INDIA INFRASTRUCTURE & LOGISTICS": "Nifty India Infrastructure & Logistics",
    "NIFTY INDIA INTERNET": "Nifty India Internet",
    "NIFTY INDIA FPI 150": "Nifty India FPI 150",
    "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP 25 CAP": "Nifty Tata Group 25% Cap",
    "NIFTY TOTAL MARKET MOMENTUM QUALITY 50": "Nifty Total Market Momentum Quality 50",
    "NIFTY500 FLEXICAP QUALITY 30": "Nifty500 Flexicap Quality 30",
    "NIFTY500 LMS EQL": "Nifty500 LargeMidSmall Equal-Cap Weighted",
    "NIFTY500 MULTICAP": "Nifty500 Multicap 50:25:25",
    "NIFTY500 MQVLV50": "Nifty500 MQ Value LowVol 50",
    "NIFTY MIDSMALLCAP400 50:50": "Nifty MidSmallcap400 50:50",
    "NIFTY WAVES": "Nifty Waves",
    "NIFTY MULTI MFG": "Nifty Multi Manufacturing",
    "NIFTY MULTI INFRA": "Nifty Multi Infrastructure",
    "NIFTY RURAL": "Nifty Rural",
}

# ---- Grouping (display convenience only, not a data value). Ordered rules: first
# match wins. Broad = size/market-cap cohorts; Sectoral = single-sector; Strategy =
# factor / smart-beta / equal-weight; Thematic = cross-sector themes; Other = bonds,
# G-Secs, SME, and anything unclassified.
BROAD = {
    "NIFTY 50",
    "NIFTY NEXT 50",
    "NIFTY 100",
    "NIFTY 200",
    "NIFTY 500",
    "NIFTY TOTAL MKT",
    "NIFTY MIDCAP 50",
    "NIFTY MIDCAP 100",
    "NIFTY MIDCAP 150",
    "NIFTY MID SELECT",
    "NIFTY SMALLCAP 50",
    "NIFTY SMLCAP 100",
    "NIFTY SMLCAP 250",
    "NIFTY SMALLCAP 500",
    "NIFTY MICROCAP250",
    "NIFTY LARGEMID250",
    "NIFTY MIDSMALLCAP 400",
    "NIFTY MIDSMALLCAP400 50:50",
}
SECTORAL = {
    "NIFTY BANK",
    "NIFTY AUTO",
    "NIFTY FMCG",
    "NIFTY IT",
    "NIFTY MEDIA",
    "NIFTY METAL",
    "NIFTY PHARMA",
    "NIFTY PSU BANK",
    "NIFTY PVT BANK",
    "NIFTY REALTY",
    "NIFTY ENERGY",
    "NIFTY FIN SERVICE",
    "NIFTY HEALTHCARE",
    "NIFTY OIL AND GAS",
    "NIFTY CONSR DURBL",
    "NIFTY CHEMICALS",
    "NIFTY CAPITAL MKT",
    "NIFTY CEMENT",
    "NIFTY FINSEREXBNK",
    "NIFTY FINSRV25 50",
}
# Substring keywords → group (checked after the explicit sets above).
STRATEGY_KW = [
    "ALPHA",
    "QUALTY",
    "QLTY",
    "QUALITY",
    "VALUE",
    "MOMENT",
    "MOMNTM",
    "LOWVOL",
    "LOW VOL",
    "LV ",
    "EQL",
    " EW",
    "500 EW",
    "HIGHBETA",
    "HIGH BETA",
    "SHARIAH",
    "ESG",
    "LIQ",
    "GROWSECT",
    "DIV OPPS",
    "AQL",
    "AQLV",
    " MQ ",
    "MQVLV",
    "MQ 50",
    "MQ 100",
    "Q50",
    "Q 50",
]
THEMATIC_KW = [
    "CONSUMPTION",
    "CONSUMP",
    "MNC",
    "PSE",
    "CPSE",
    "SERV SECTOR",
    "INFRA",
    "MFG",
    "MANUFACT",
    "RAILWAY",
    "DEFENCE",
    "DIGITAL",
    "INTERNET",
    "EV",
    "MOBILITY",
    "HOUSING",
    "TOURISM",
    "RURAL",
    "REITS",
    "TRANS LOGIS",
    "NONCYC",
    "MULTI INFRA",
    "CONGLOMERATE",
    "TATA GROUP",
    "IPO",
    "WAVES",
    "MAATR",
    "COMMODITIES",
    "COREHOUSING",
    "MS IT",
    "MS FIN",
    "MS IND",
    "MIDSML HLTH",
    "NEW CONSUMP",
    "FPI",
    "TRANSPORT",
    "CORE HOUSING",
]
OTHER_KW = ["BHARATBOND", "GS ", "G-SEC", "GSEC", "SME", "SDL", "BOND"]


def _label(name):
    if name in LABELS:
        return LABELS[name]
    parts = name.title().split()
    if parts and parts[0].lower() == "nifty":
        parts[0] = "Nifty"
    return " ".join(parts)


def _group(name):
    n = name.upper()
    if any(k in n for k in OTHER_KW):
        return "other"
    if n in BROAD:
        return "broad"
    if n in SECTORAL:
        return "sectoral"
    if any(k in n for k in THEMATIC_KW):
        return "thematic"
    if any(k in n for k in STRATEGY_KW):
        return "strategy"
    return "other"


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _pct_rank(samples, cur):
    """Percentile (0-100) of `cur` within its own history. Higher = more expensive
    than usual. None if too little history to be meaningful."""
    xs = [x for x in samples if isinstance(x, (int, float)) and x > 0]
    if cur is None or cur <= 0 or len(xs) < 40:
        return None
    below = sum(1 for x in xs if x <= cur)
    return round(100.0 * below / len(xs))


def _fetch_live():
    req = urllib.request.Request(LIVE_URL, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=60))["data"]


def _fetch_nse_valuation():
    """({indexName_upper: {pe,pb,dy,c30,c365}}, [suppressed]) from NSE allIndices.
    Best-effort; ({}, []) on any failure (403 from raw IPs is normal — CI fills it).

    ⚠️ perChange365d / perChange30d use 0 as a NO-BASE SENTINEL, not a real return.
    An index younger than the window comes back with perChange365d == 0 alongside
    oneYearAgoVal == 0, date365dAgo == null and chart365dPath == null — NSE saying
    "I have no value a year ago", not "this index is flat over a year". Left alone it
    renders as a confident "0.0%" on the page (found live 2026-08-10 on NIFTY
    MIDSMALLCAP400 50:50, next to Nifty Midcap Select's correct "—").

    Measured from the payload itself, not assumed — CI probe of /api/allIndices on
    2026-08-10, all 139 indices: exactly 10 carried perChange365d == 0, and all 10
    had oneYearAgoVal == 0 + date365dAgo null + chart365dPath null. NOT ONE index
    reported perChange365d == 0 with a real base. The 30d field was clean (every
    oneMonthAgoVal was a real level; the one perChange30d == 0, NIFTY FMCG, had a
    real base) — it is handled symmetrically so the class can't appear there unseen.

    Suppress only on the CONJUNCTION — exact 0 AND a missing base — because neither
    half is sufficient alone:
      * empty base alone is NOT enough: NIFTY50 USD reports oneYearAgoVal == 0 and
        date365dAgo null yet a real perChange365d of -7.14; nulling on the base
        would throw a good number away.
      * exact 0 alone is NOT enough: a genuinely flat year rounds to 0.00 legally,
        and it comes with a real base.
    """
    if B is None:
        return {}, []
    try:
        hdr = {
            "User-Agent": B.UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/market-data/live-equity-market",
        }
        j = json.loads(B._get("https://www.nseindia.com/api/allIndices", headers=hdr, jar=B.nse_jar(), timeout=30))
    except Exception as e:
        print(f"NSE allIndices unavailable ({type(e).__name__}) — PE/PB/DY left to prior values")
        return {}, []
    out, suppressed = {}, []
    for r in j.get("data", []):
        key = str(r.get("index", "")).strip().upper()
        if not key:
            continue
        c30, c365 = _num(r.get("perChange30d")), _num(r.get("perChange365d"))
        if c365 == 0 and not _num(r.get("oneYearAgoVal")):
            suppressed.append(key + " 1Y")
            c365 = None  # no base → unknown, NOT zero (falls back to our history)
        if c30 == 0 and not _num(r.get("oneMonthAgoVal")):
            suppressed.append(key + " 1M")
            c30 = None
        out[key] = {
            "pe": _num(r.get("pe")),
            "pb": _num(r.get("pb")),
            "dy": _num(r.get("dy")),
            "c30": c30,
            "c365": c365,
        }
    return out, suppressed


# NSE allIndices spells a handful of names differently from the live watch; map the
# live-watch key to the allIndices key so PE/PB/DY join.
NSE_ALIAS = {
    "NIFTY SMLCAP 100": "NIFTY SMALLCAP 100",
    "NIFTY SMLCAP 250": "NIFTY SMALLCAP 250",
    "NIFTY MICROCAP250": "NIFTY MICROCAP 250",
    "NIFTY PVT BANK": "NIFTY PRIVATE BANK",
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",
    "NIFTY OIL AND GAS": "NIFTY OIL & GAS",
    "NIFTY CONSR DURBL": "NIFTY CONSUMER DURABLES",
    "NIFTY TOTAL MKT": "NIFTY TOTAL MARKET",
    "NIFTY CONSUMPTION": "NIFTY INDIA CONSUMPTION",
    "NIFTY IND DEFENCE": "NIFTY INDIA DEFENCE",
    "NIFTY LARGEMID250": "NIFTY LARGEMIDCAP 250",
}


def _member_data():
    """({name_upper: count}, {name_upper: [symbols]}) from the latest snapshot in
    scripts/indices_history.json (for the drill-down)."""
    try:
        hist = json.load(open(MEMBERS, encoding="utf-8"))
    except Exception:
        return {}, {}
    counts, members = {}, {}
    for idx, snaps in hist.items():
        if not snaps:
            continue
        latest = max(snaps, key=lambda s: s.get("effectiveDate", ""))
        syms = latest.get("symbols") or []
        counts[idx.strip().upper()] = len(syms)
        members[idx.strip().upper()] = syms
    return counts, members


def main():
    try:
        rows = _fetch_live()
    except Exception as e:  # fail-soft: keep yesterday's files
        print("live fetch failed, feeds left untouched:", repr(e))
        return 0

    hist = {"daily": {}, "pe": {}, "pb": {}, "dy": {}}
    if os.path.exists(HIST):
        with contextlib.suppress(Exception):
            hist = json.load(open(HIST, encoding="utf-8"))
    hist.setdefault("daily", {})
    for k in ("pe", "pb", "dy"):
        hist.setdefault(k, {})

    nse, nse_nobase = _fetch_nse_valuation()
    if nse_nobase:
        print(
            "NSE no-base sentinel suppressed (0 -> null) on %d field(s): %s"
            % (len(nse_nobase), ", ".join(sorted(nse_nobase)))
        )
    mcount, members = _member_data()

    # --- session date from the feed's own timeVal (never the wall clock) ---
    asof = None
    for r in rows:
        tv = str(r.get("timeVal", "")).strip()  # "20-Jul-2026 12:48"
        try:
            d, mon, rest = tv.split("-")
            ds = "%04d-%02d-%02d" % (int(rest.split()[0]), MONTHS[mon], int(d))
            if asof is None or ds > asof:
                asof = ds
        except Exception:
            continue
    if not asof:
        print("no parseable timeVal — feeds left untouched")
        return 0

    # --- write today's closes + valuation samples into the rolling history ---
    day = hist["daily"].setdefault(asof, {})
    for r in rows:
        name = str(r.get("indexName", "")).strip()
        last = _num(r.get("last"))
        if not name or last is None or last <= 0:
            continue
        day[name] = round(last, 2)
        v = nse.get(name.upper()) or nse.get(NSE_ALIAS.get(name.upper(), ""))
        if v:
            for k in ("pe", "pb", "dy"):
                if v.get(k) is not None and v[k] > 0:
                    hist[k].setdefault(name, {})[asof] = v[k]

    # trim rolling windows (oldest first)
    for d in sorted(hist["daily"])[:-DAILY_KEEP]:
        hist["daily"].pop(d)
    for k in ("pe", "pb", "dy"):
        for name, series in hist[k].items():
            for d in sorted(series)[:-PEPB_KEEP]:
                series.pop(d)

    dates = sorted(hist["daily"])  # ascending trading sessions we hold
    di = {d: i for i, d in enumerate(dates)}

    def close_back(name, sessions):
        i = di[asof] - sessions
        return hist["daily"][dates[i]].get(name) if i >= 0 else None

    def change_back(name, cur, sessions):
        base = close_back(name, sessions)
        return round(100.0 * (cur - base) / base, 2) if (base and base > 0 and cur) else None

    # Nifty 50 anchors relative strength.
    n50_last = day.get("NIFTY 50")
    n50 = nse.get("NIFTY 50") or {}

    def nifty_change(win_days, field):
        return n50.get(field) if n50.get(field) is not None else change_back("NIFTY 50", n50_last, win_days)

    n50_1m = nifty_change(21, "c30")
    n50_1y = nifty_change(250, "c365")

    out_indices = []
    for r in rows:
        name = str(r.get("indexName", "")).strip()
        last = _num(r.get("last"))
        if not name or last is None or last <= 0:
            continue
        v = nse.get(name.upper()) or nse.get(NSE_ALIAS.get(name.upper(), "")) or {}
        pc = _num(r.get("percChange"))
        m1 = v.get("c30")
        if m1 is None:
            m1 = change_back(name, last, 21)
        y1 = v.get("c365")
        if y1 is None:
            y1 = change_back(name, last, 250)
        w1 = change_back(name, last, 5)

        yh, yl = _num(r.get("yearHigh")), _num(r.get("yearLow"))
        pos52 = None
        if yh and yl and yh > yl:
            pos52 = max(0, min(100, round(100.0 * (last - yl) / (yh - yl))))

        spark = [hist["daily"][d][name] for d in dates[-SPARK_N:] if name in hist["daily"][d]]

        pe, pb, dy = v.get("pe"), v.get("pb"), v.get("dy")
        pep = _pct_rank(list(hist["pe"].get(name, {}).values()), pe)
        pbp = _pct_rank(list(hist["pb"].get(name, {}).values()), pb)

        rs1m = round(m1 - n50_1m, 2) if (m1 is not None and n50_1m is not None) else None
        rs1y = round(y1 - n50_1y, 2) if (y1 is not None and n50_1y is not None) else None

        key = name.upper()
        rec = {
            "k": name,
            "n": _label(name),
            "g": _group(name),
            "last": round(last, 2),
            "pc": pc,
            "w1": w1,
            "m1": m1,
            "y1": y1,
            "pe": pe,
            "pb": pb,
            "dy": dy,
            "pep": pep,
            "pbp": pbp,
            "yh": yh,
            "yl": yl,
            "pos52": pos52,
            "rs1m": rs1m,
            "rs1y": rs1y,
            "spark": [round(x, 2) for x in spark],
        }
        mc = mcount.get(key) or mcount.get(NSE_ALIAS.get(key, ""))
        if mc:
            rec["mem"] = mc
            ms = members.get(key) or members.get(NSE_ALIAS.get(key, ""))
            if ms:
                rec["members"] = ms
        out_indices.append(rec)

    if len(out_indices) < 50:
        print("only %d indices parsed — refusing to write (guard)" % len(out_indices))
        return 0

    # §39 regression check for the no-base sentinel: every 1M/1Y value that survives
    # as exactly 0.00 must trace to a real base — NSE's (verified above) or a real
    # close in our own rolling history. List them, so if the suppression above ever
    # regresses the whole young-index cohort shows up here instead of quietly
    # rendering "0.0%" on the page.
    flat = ["{} {}".format(x["k"], f) for x in out_indices for f in ("m1", "y1") if x[f] == 0]
    print("exactly-0.00 change values (all base-backed): %s" % (", ".join(flat) or "none"))

    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now = dt.datetime.now(ist).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    grp_order = {"broad": 0, "sectoral": 1, "strategy": 2, "thematic": 3, "other": 4}
    out_indices.sort(key=lambda x: (grp_order.get(x["g"], 9), -(x["pc"] if x["pc"] is not None else -999)))

    payload = {
        "asof": asof,
        "updated": now,
        "have_valn": bool(nse),
        "n50_1m": n50_1m,
        "n50_1y": n50_1y,
        "groups": ["broad", "sectoral", "strategy", "thematic", "other"],
        "group_labels": {
            "broad": "Broad Market",
            "sectoral": "Sectoral",
            "strategy": "Strategy / Factor",
            "thematic": "Thematic",
            "other": "Bonds & Other",
        },
        "indices": out_indices,
    }

    hist["updated"] = now
    json.dump(hist, open(HIST, "w", encoding="utf-8"), separators=(",", ":"))
    json.dump(payload, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(
        "wrote %d indices %s; asof %s"
        % (len(out_indices), "with PE/PB/DY" if nse else "levels only (NSE valn skipped)", asof)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
