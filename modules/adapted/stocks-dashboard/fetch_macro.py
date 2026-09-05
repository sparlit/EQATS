#!/usr/bin/env python3
"""Fetch the macro dashboard series -> docs/macro.json.

Powers docs/macro.html (Market strength / Valuation / Rates & currency / Economy).
Everything here is the NEW data the page needs; the page reads the already-existing
rich feeds (market_breadth.json, fii_dii.json, nifty.json, india_vix.json,
index_monthly.json, bank_credit.json) directly and does not duplicate them here.

SOURCES (all keyless, reachable from GitHub runners):
  * Yahoo Finance chart API  -> US 10Y (^TNX), USD/INR (INR=X), ICE dollar index
      (DX-Y.NYB), Brent crude (BZ=F), gold (GC=F, converted to Rs/10g via USD/INR).
  * mql5 economic-calendar /export TSV (same feed as fetch_bank_credit.py) -> CPI,
      IIP, GDP, RBI repo rate, M3 y/y, deposit growth y/y, forex reserves.
  * FRED CSV -> India 10Y G-Sec (INDIRLTLT01STM, monthly). Best-effort: FRED is
      US-hosted and can be unreachable from some IPs, so a failure just keeps the
      existing series (self-heals next run).
  * NSE allIndices -> current Nifty 50 PE / PB / dividend-yield (appended daily;
      deep history is seeded separately from niftyindices — see runbook).

CUMULATIVE: every series is a {date: value} map merged into the existing file, so a
skipped or partially-failed run never shrinks the data and self-heals next run.

stdlib only + build_fundamentals (for the shared NSE cookie-primed opener).
"""
import datetime
import gzip
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "macro.json")
UA = B.UA

# ---- series catalogue (label/unit/source shown on the page) -------------------
META = {
    "us10y":   {"label": "US 10Y yield",            "unit": "%",       "src": "Yahoo ^TNX"},
    "india10y":{"label": "India 10Y G-Sec yield",   "unit": "%",       "src": "FRED, monthly"},
    "usdinr":  {"label": "USD/INR",                 "unit": "",        "src": "Yahoo"},
    "dxy":     {"label": "US dollar index (DXY)",   "unit": "",        "src": "Yahoo DX-Y.NYB"},
    "crude":   {"label": "Brent crude",             "unit": "$/bbl",   "src": "Yahoo BZ=F"},
    "gold":    {"label": "Gold",                    "unit": "Rs/10g",  "src": "Yahoo GC=F x USDINR"},
    "niftype": {"label": "Nifty 50 PE",             "unit": "",        "src": "NSE / niftyindices"},
    "niftypb": {"label": "Nifty 50 PB",             "unit": "",        "src": "NSE / niftyindices"},
    "niftydy": {"label": "Nifty 50 dividend yield", "unit": "%",       "src": "NSE / niftyindices"},
    "repo":    {"label": "RBI repo rate",           "unit": "%",       "src": "RBI (mql5)"},
    "cpi":     {"label": "CPI inflation",           "unit": "% y/y",   "src": "MOSPI (mql5), monthly"},
    "iip":     {"label": "Industrial production (IIP)", "unit": "% y/y", "src": "MOSPI (mql5), monthly"},
    "gdp":     {"label": "GDP growth",              "unit": "% y/y",   "src": "MOSPI (mql5), quarterly"},
    "m3":      {"label": "Money supply M3",         "unit": "% y/y",   "src": "RBI (mql5), weekly"},
    "deposits":{"label": "Deposit growth",          "unit": "% y/y",   "src": "RBI (mql5), weekly"},
    "forex":   {"label": "Forex reserves",          "unit": "$ bn",    "src": "RBI (mql5), weekly"},
    # ---- v2 additions (2026-07-18) ----
    "silver":  {"label": "Silver",                  "unit": "Rs/kg",   "src": "Yahoo SI=F x USDINR"},
    "copper":  {"label": "Copper",                  "unit": "$/lb",    "src": "Yahoo HG=F"},
    "spx":     {"label": "S&P 500",                 "unit": "",        "src": "Yahoo ^GSPC"},
    "nasdaq":  {"label": "Nasdaq Composite",        "unit": "",        "src": "Yahoo ^IXIC"},
    "nikkei":  {"label": "Nikkei 225",              "unit": "",        "src": "Yahoo ^N225"},
    "hsi":     {"label": "Hang Seng",               "unit": "",        "src": "Yahoo ^HSI"},
    "wpi":     {"label": "WPI inflation",           "unit": "% y/y",   "src": "mql5, monthly"},
    "trade":   {"label": "Trade balance",           "unit": "$ bn",    "src": "mql5, monthly"},
    "pmimfg":  {"label": "Manufacturing PMI",       "unit": "",        "src": "S&P Global (mql5)"},
    "pmisvc":  {"label": "Services PMI",            "unit": "",        "src": "S&P Global (mql5)"},
    "usffr":   {"label": "US Fed funds rate",       "unit": "%",       "src": "Fed (mql5)"},
    "uscpi":   {"label": "US CPI inflation",        "unit": "% y/y",   "src": "BLS (mql5)"},
    "gdpn":    {"label": "India nominal GDP",       "unit": "Rs lakh cr", "src": "MOSPI, FY (seeded)"},
    "mcaptot": {"label": "Listed market cap",       "unit": "Rs lakh cr", "src": "our tracked universe, daily"},
}

# Yahoo symbol -> series key (URL-encoded symbol)
YH = {
    "us10y":  "%5ETNX",
    "usdinr": "INR%3DX",
    "dxy":    "DX-Y.NYB",
    "crude":  "BZ%3DF",
    "goldusd": "GC%3DF",   # gold in USD/oz — converted to Rs/10g below
    "silverusd": "SI%3DF", # silver in USD/oz — converted to Rs/kg below
    "copper": "HG%3DF",
    "spx":    "%5EGSPC",
    "nasdaq": "%5EIXIC",
    "nikkei": "%5EN225",
    "hsi":    "%5EHSI",
}
# series key -> (mql5 country, slug)
MQ = {
    "repo":     ("india", "rbi-interest-rate-decision"),
    "cpi":      ("india", "cpi-yy"),
    "iip":      ("india", "industrial-production-yy"),
    "gdp":      ("india", "gdp-yy"),
    "m3":       ("india", "rbi-m3-money-supply-yy"),
    "deposits": ("india", "deposit-growth-yy"),
    "forex":    ("india", "foreign-exchange-reserves"),
    "wpi":      ("india", "wpi-yy"),
    "trade":    ("india", "trade-balance"),
    "pmimfg":   ("india", "markit-manufacturing-pmi"),
    "pmisvc":   ("india", "markit-services-pmi"),
    "usffr":    ("united-states", "fed-interest-rate-decision"),
    "uscpi":    ("united-states", "consumer-price-index-yy"),
}
MQ_BASE = "https://www.mql5.com/en/economic-calendar/"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
OZ_TO_10G = 10.0 / 31.1034768   # troy oz -> 10 grams
OZ_TO_KG = 1000.0 / 31.1034768  # troy oz -> kilogram

# India nominal GDP, Rs lakh crore, current prices (MOSPI National Accounts), dated at FY end.
# Approximate to the latest revision; FY26 = budget estimate. Update once a year when the
# provisional estimate lands (late May) — the merge is cumulative so edits self-apply.
GDP_NOMINAL = {
    "2013-03-31": 99.44,  "2014-03-31": 112.34, "2015-03-31": 124.68,
    "2016-03-31": 137.72, "2017-03-31": 153.92, "2018-03-31": 170.90,
    "2019-03-31": 188.87, "2020-03-31": 201.04, "2021-03-31": 198.29,
    "2022-03-31": 236.60, "2023-03-31": 269.50, "2024-03-31": 295.36,
    "2025-03-31": 330.68, "2026-03-31": 356.97,
}


def _num(x):
    x = (x or "").strip().replace("%", "").replace(",", "")
    try:
        return float(x)
    except ValueError:
        return None


def fetch_yahoo(sym):
    """{date: close} full daily history since 2012 for a Yahoo symbol."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
           "?period1=1325376000&period2=" + str(int(time.time())) + "&interval=1d")
    j = json.loads(B._get(url, headers={"User-Agent": UA}, timeout=30))
    res = j["chart"]["result"][0]
    out = {}
    for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if c is None:
            continue
        out[time.strftime("%Y-%m-%d", time.gmtime(t))] = c
    return out


def fetch_mql5(country, slug):
    """{date: value} full history from the mql5 economic-calendar export TSV."""
    page = MQ_BASE + country + "/" + slug
    url = page + "/export"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/csv,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9", "Referer": page})
    tsv = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    out = {}
    for line in tsv.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("date"):
            continue
        p = line.split("\t")
        if len(p) < 2:
            continue
        date = p[0].strip().replace(".", "-").replace("/", "-")
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            continue
        v = _num(p[1])
        if v is not None:
            out[date] = v
    return out


def fetch_fred(sid):
    """{date: value} from a FRED CSV (skips '.' missing markers)."""
    b = urllib.request.urlopen(
        urllib.request.Request(FRED + sid, headers={"User-Agent": UA}), timeout=20
    ).read().decode("utf-8", "replace")
    out = {}
    for line in b.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 2:
            continue
        v = _num(p[1])
        if v is not None:
            out[p[0].strip()] = v
    return out


def fetch_nifty_valuation(jar):
    """Current Nifty 50 PE/PB/DY from NSE allIndices -> {key: (date, val)}."""
    hdr = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
           "Referer": "https://www.nseindia.com/market-data/live-equity-market"}
    j = json.loads(B._get("https://www.nseindia.com/api/allIndices",
                          headers=hdr, jar=jar, timeout=30))
    today = datetime.date.today().isoformat()
    out = {}
    for d in j.get("data", []):
        if str(d.get("index", "")).upper() == "NIFTY 50":
            for key, fld in (("niftype", "pe"), ("niftypb", "pb"), ("niftydy", "dy")):
                v = _num(str(d.get(fld, "")))
                if v is not None and v > 0:
                    out[key] = (today, v)
    return out


def fetch_mcap_total():
    """Today's total market cap of our tracked universe (Rs lakh cr) from dash_slim.bin.
    Sanity-guarded so a truncated bin can never poison the series."""
    p = os.path.join(ROOT, "docs", "dash_slim.bin")
    slim = json.loads(gzip.decompress(open(p, "rb").read()))
    tot, n = 0.0, 0
    for m in (slim.get("meta") or {}).values():
        v = m.get("mcap")
        if isinstance(v, (int, float)) and v > 0:
            tot += v
            n += 1
    if n < 1500:
        raise ValueError("dash_slim mcap rows too few: %d" % n)
    lakh_cr = tot / 1e5   # mcap is Rs cr -> Rs lakh cr
    if not (100 < lakh_cr < 5000):
        raise ValueError("mcap total implausible: %.1f lakh cr" % lakh_cr)
    return {datetime.date.today().isoformat(): lakh_cr}


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"series": {}}


def _merge(dst, key, add, rnd=2):
    """Merge {date: value} `add` into series `key` of dst (cumulative, newest wins)."""
    s = dst["series"].setdefault(key, {})
    d = s.setdefault("d", {})
    for date, val in add.items():
        d[date] = round(val, rnd)
    m = META.get(key, {})
    s["label"], s["unit"], s["src"] = m.get("label", key), m.get("unit", ""), m.get("src", "")


def main():
    out = load_existing()
    out.setdefault("series", {})
    ok, fail = [], []

    # --- Yahoo (rates + commodities) ---
    yh = {}
    for key, sym in YH.items():
        try:
            yh[key] = fetch_yahoo(sym)
            ok.append("yh:" + key)
        except Exception as e:
            fail.append("yh:%s (%s)" % (key, str(e)[:60]))
    for key in ("us10y", "usdinr", "dxy", "crude", "copper", "spx", "nasdaq", "nikkei", "hsi"):
        if yh.get(key):
            _merge(out, key, yh[key], rnd=3 if key in ("usdinr", "copper") else 2)
    # gold/silver: USD/oz -> Rs/10g / Rs/kg using same-day USD/INR (fallback: latest INR)
    inr = yh.get("usdinr") or {}
    last_inr = inr[max(inr)] if inr else None
    for ykey, skey, factor in (("goldusd", "gold", OZ_TO_10G), ("silverusd", "silver", OZ_TO_KG)):
        if yh.get(ykey) and inr:
            conv = {}
            for date, usd in yh[ykey].items():
                rate = inr.get(date, last_inr)
                if rate:
                    conv[date] = usd * rate * factor
            if conv:
                _merge(out, skey, conv, rnd=0)

    # --- mql5 (economy, India + US) ---
    for key, (country, slug) in MQ.items():
        try:
            _merge(out, key, fetch_mql5(country, slug), rnd=1)
            ok.append("mq:" + key)
        except Exception as e:
            fail.append("mq:%s (%s)" % (key, str(e)[:60]))

    # --- Buffett-indicator inputs: GDP seed (idempotent) + today's total mcap ---
    _merge(out, "gdpn", GDP_NOMINAL, rnd=2)
    try:
        _merge(out, "mcaptot", fetch_mcap_total(), rnd=1)
        ok.append("mcaptot")
    except Exception as e:
        fail.append("mcaptot (%s)" % str(e)[:60])

    # --- FRED (India 10Y, best-effort) ---
    try:
        _merge(out, "india10y", fetch_fred("INDIRLTLT01STM"), rnd=2)
        ok.append("fred:india10y")
    except Exception as e:
        fail.append("fred:india10y (%s)" % str(e)[:60])

    # --- NSE valuation (current PE/PB/DY) ---
    try:
        for key, (date, val) in fetch_nifty_valuation(B.nse_jar()).items():
            _merge(out, key, {date: val}, rnd=2)
            ok.append("nse:" + key)
    except Exception as e:
        fail.append("nse:valuation (%s)" % str(e)[:60])

    if not out["series"]:
        print("ERROR no data at all — not writing", file=sys.stderr)
        sys.exit(1)

    out["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["source"] = ("Yahoo Finance, mql5 economic calendar (RBI/MOSPI), FRED, "
                     "NSE allIndices / niftyindices")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    counts = {k: len(v.get("d", {})) for k, v in out["series"].items()}
    print("wrote docs/macro.json | series:", counts)
    print("OK:", ", ".join(ok))
    if fail:
        print("FAILED:", "; ".join(fail), file=sys.stderr)


if __name__ == "__main__":
    main()
