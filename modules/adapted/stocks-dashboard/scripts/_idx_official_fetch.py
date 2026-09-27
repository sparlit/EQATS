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
"""Fetch EVERY official archived NSE/niftyindices sub-index constituent CSV.

These are the ONLY ground-truth point-in-time memberships for the 8 broad tiers
(+ Nifty Bank since 2026-09-21, runbook section 141a: its 2017-2020 rosters were
scrapbook junk — PAYTM, KINDIA — because it had no pins and no pre-2021 events).
CDX-enumerate all 200-status captures for each tier's niftyindices slug AND its
CNX-era predecessor, fetch+parse each, plus grab the live current list.

Writes _idx_official_snaps.json = {tier: {YYYYMMDD: [symbols]}} (symbols direct,
authoritative, no name resolution needed).

Run:  python3 _idx_official_fetch.py                 # every tier, rewrites the file
      python3 _idx_official_fetch.py --only "Nifty Bank"   # one tier, MERGED into the existing file
"""
import csv
import gzip
import io
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as cr

UA = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}

# tier -> list of (host_path) to try; niftyindices current + CNX predecessor + nse archives
NI = "niftyindices.com/IndexConstituent/ind_%slist.csv"
NSE = "nseindia.com/content/indices/ind_%slist.csv"
ARC = "archives.nseindia.com/content/indices/ind_%slist.csv"


def paths(slug, *extra):
    """niftyindices (2017-), nseindia (2016-2020), archives.nseindia (2021-) + CNX-era file names"""
    return [NI % slug, NSE % slug, ARC % slug] + [NSE % e for e in extra]


# tier -> archive paths to enumerate. 2026-09-21 (runbook section 141c): every tracked index, each
# with its current file name on the three NSE hosts plus its CNX-era predecessor file(s).
TIERS = {
    "Nifty 100": paths("nifty100", "cnx100"),
    "Nifty Midcap 100": paths("niftymidcap100", "cnxmidcap"),
    "Nifty Midcap 50": paths("niftymidcap50", "cnxmidcap50"),
    "Nifty Smallcap 100": paths("niftysmallcap100", "cnxsmallcap"),
    "Nifty Midcap 150": paths("niftymidcap150"),
    "Nifty Smallcap 250": paths("niftysmallcap250"),
    "Nifty Smallcap 50": paths("niftysmallcap50"),
    "Nifty LargeMidcap 250": paths("niftylargemidcap250"),
    "Nifty MidSmallcap 400": paths("niftymidsmallcap400"),
    # sector index: 12 names 2006-2025, 14 from 2025-12-31 (ind_prs01122025). CNX-era captures
    # 2006-2015 carry the then-tickers (UTIBANK, ORIENTBANK, CORPBANK, SYNDIBANK ...) - the
    # membership builder's canon()/era_key handles them like every other tier.
    "Nifty Bank": paths("niftybank", "cnxbank"),
    # 2026-09-21 (runbook section 141b): the flagship's own history began 2015-09-28; the S&P CNX
    # Nifty-era file (ind_niftylist.csv, 2006-2020) + the nifty50list captures pin it 2006-2026.
    "Nifty 50": paths("nifty50", "nifty"),
    "Nifty Next 50": paths("niftynext50", "junior", "cnxniftyjunior"),
    "Nifty 200": paths("nifty200", "cnx200"),
    "Nifty IT": paths("niftyit", "cnxit"),
    "Nifty Pharma": paths("niftypharma", "cnxpharma"),
    "Nifty Auto": paths("niftyauto", "cnxauto"),
    "Nifty FMCG": paths("niftyfmcg", "cnxfmcg"),
    "Nifty Metal": paths("niftymetal", "cnxmetal"),
    "Nifty Energy": paths("niftyenergy", "cnxenergy"),
    "Nifty Realty": paths("niftyrealty", "cnxrealty"),
    "Nifty Media": paths("niftymedia", "cnxmedia"),
    "Nifty PSU Bank": paths("niftypsubank", "cnxpsubank"),
    "Nifty MNC": paths("niftymnc", "cnxmnc"),
    "Nifty Healthcare": paths("niftyhealthcare"),
    "Nifty Consumer Durables": paths("niftyconsumerdurables"),
    "Nifty Oil & Gas": paths("niftyoilgas"),
}
# a capture must carry at least this many names to count as a full list (guards truncated pages)
MIN_NAMES = {
    "Nifty Bank": 10,
    "Nifty 50": 45,
    "Nifty Next 50": 45,
    "Nifty 100": 90,
    "Nifty 200": 180,
    "Nifty Midcap 50": 45,
    "Nifty Midcap 100": 90,
    "Nifty Smallcap 50": 45,
    "Nifty Smallcap 100": 90,
    "Nifty Midcap 150": 135,
    "Nifty Smallcap 250": 225,
    "Nifty LargeMidcap 250": 225,
    "Nifty MidSmallcap 400": 360,
    "Nifty IT": 8,
    "Nifty Pharma": 8,
    "Nifty Auto": 10,
    "Nifty FMCG": 10,
    "Nifty Metal": 10,
    "Nifty Energy": 8,
    "Nifty Realty": 8,
    "Nifty Media": 8,
    "Nifty PSU Bank": 8,
    "Nifty MNC": 12,
    "Nifty Healthcare": 15,
    "Nifty Consumer Durables": 10,
    "Nifty Oil & Gas": 10,
}
DEFAULT_MIN = 30
# live current filenames (niftyindices serves these)
LIVE = {
    t: "https://www.niftyindices.com/IndexConstituent/ind_{}list.csv".format(
        t.lower().replace("nifty ", "nifty").replace(" ", "").replace("&", "")
    )
    for t in TIERS
}


# --- Wayback enumeration: ONE prefix query per NSE directory, cached, then filtered per file ---
# (2026-09-21: ~100 per-file CDX queries throttled under parallel workers and tiers silently lost
# captures; a directory prefix query returns every capture of every list file in one call.)
_ENUM = {}
_ENUM_LOCK = threading.Lock()
DIRS = ("niftyindices.com/IndexConstituent/", "nseindia.com/content/indices/", "archives.nseindia.com/content/indices/")


def cdx_dir(d):
    q = (
        f"https://web.archive.org/cdx/search/cdx?url={d}&matchType=prefix&output=json"
        "&filter=statuscode:200&collapse=digest&fl=timestamp,original"
    )
    last = None
    for i in range(6):
        try:
            rows = json.load(urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=180))[1:]
            print("  CDX %s: %d captures" % (d, len(rows)), flush=True)
            return rows
        except Exception as e:
            last = e
            time.sleep(8 * (i + 1))
    print(f"  CDX FAILED for {d} after 6 tries: {str(last)[:80]}", flush=True)
    return None


def cdx(path):
    """captures of one list file: [(timestamp, original)] from the cached directory listing"""
    d = [x for x in DIRS if path.startswith(x)]
    if not d:
        return []
    d = d[0]
    with _ENUM_LOCK:
        if d not in _ENUM:
            _ENUM[d] = cdx_dir(d)
    rows = _ENUM[d] or []
    fname = path.split("/")[-1].lower()
    hits = [("", ts, orig) for ts, orig in rows if orig.lower().rstrip("/").endswith("/" + fname)]
    if hits:
        return hits
    # the directory listing missed this file (measured 2026-09-22: it listed 5,799 nseindia captures
    # but none of ind_cnx100list.csv's 12, which a per-file query returns) - ask for the file itself
    q = (
        f"https://web.archive.org/cdx/search/cdx?url={path}&output=json&filter=statuscode:200"
        "&collapse=digest&fl=timestamp,original"
    )
    for i in range(4):
        try:
            rows = json.load(urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=90))[1:]
            if rows:
                print("  per-file CDX %s: %d captures the directory listing lacked" % (path, len(rows)), flush=True)
            return [("", ts, orig) for ts, orig in rows]
        except Exception:
            time.sleep(6 * (i + 1))
    print(f"  CDX FAILED for {path} (per-file fallback)", flush=True)
    return []


def parse_csv(txt):
    """Symbols from an NSE constituent CSV. The column is located from the header row when one
    exists ("Symbol"): the 2006-era CNX lists are (Company Name, Symbol, Series) with a title row
    above, the later ones (Company Name, Industry, Symbol, Series, ISIN). Falls back to column 2."""
    rows = list(csv.reader(io.StringIO(txt)))
    si = 2
    for row in rows:
        cells = [c.strip().lower() for c in row]
        if "symbol" in cells:
            si = cells.index("symbol")
            break
    syms = []
    for row in rows:
        if len(row) <= si:
            continue
        v = row[si].strip()
        if not v or v.lower() in ("symbol", "series", "eq") or row[0].strip() in ("", "Company Name"):
            continue
        if row[0].strip().lower().startswith("constituents"):
            continue
        syms.append(v)
    return syms


def read_capture(ts, orig):
    raw = urllib.request.urlopen(
        urllib.request.Request(f"https://web.archive.org/web/{ts}id_/{orig}", headers=UA), timeout=45
    ).read()
    if raw[:2] == b"\x1f\x8b":  # some captures are stored gzip-encoded (2026-08-27 bank list)
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_idx_official_snaps.json")
only = None
if len(sys.argv) >= 3 and sys.argv[1] == "--only":
    only = sys.argv[2:]
    bad = [t for t in only if t not in TIERS]
    if bad:
        msg = "unknown tier(s) {} - known: {}".format(bad, ", ".join(TIERS))
        raise SystemExit(msg)

try:
    _prev = json.load(open(OUT))
except Exception:
    _prev = {}
_lock = threading.Lock()


def fetch_tier(tier):
    """One tier: enumerate every archive path, parse each capture, plus the live list. Returns the
    tier's {YYYYMMDD|LIVE: [symbols]} — starting from the committed captures under --only so a
    Wayback timeout on this run never drops a list that was fetched fine before."""
    got = dict(_prev.get(tier, {})) if only else {}
    mn = MIN_NAMES.get(tier, DEFAULT_MIN)
    for path in TIERS[tier]:
        for ts, orig in [(r[1], r[2]) for r in cdx(path)]:
            d = ts[:8]
            if d in got:
                continue
            try:
                raw = read_capture(ts, orig)
            except Exception:
                continue
            s = parse_csv(raw)
            if len(s) >= mn:
                got[d] = s
    try:
        raw = cr.get(LIVE[tier], impersonate="chrome", timeout=30, headers={"Accept-Encoding": "identity"}).text
        s = parse_csv(raw)
        if len(s) >= mn:
            got["LIVE"] = s
    except Exception:
        pass
    dates = sorted(got)
    print(
        "%-24s %2d snapshots: %s" % (tier, len(got), ", ".join("%s(%d)" % (d, len(got[d])) for d in dates)), flush=True
    )
    return tier, got


todo = [t for t in TIERS if not only or t in only]
snaps = {} if only else {}
# 2026-09-21: tiers in parallel (4 workers; Wayback tolerates it) and the file is rewritten after
# EVERY tier so an interrupted run keeps what it fetched.
with ThreadPoolExecutor(max_workers=4) as ex:
    for tier, got in ex.map(fetch_tier, todo):
        with _lock:
            if only:
                _prev[tier] = got
                json.dump(_prev, open(OUT, "w"))
            else:
                snaps[tier] = got
if not only:
    json.dump(snaps, open(OUT, "w"))
print("\nwrote %s (%d tiers)" % (OUT, len(_prev if only else snaps)))
