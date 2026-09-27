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
"""Fetch sector/industry metadata for every BSE-listed stock.

We pull from BSE's `ComHeadernew/w` endpoint (the same one that powers their
own scrip-detail pages). Each response carries up to 5 classification fields
in decreasing granularity:

    Sector        -> "Commodities"
    IndustryNew   -> "Chemicals"
    IGroup        -> "Chemicals & Petrochemicals"
    Industry      -> "Commodity Chemicals"
    ISubGroup     -> "Commodity Chemicals"

Older versions of this script discarded a row unless `Sector` was non-empty.
That dropped a lot of legit data (BSE sometimes nulls Sector but populates
the rest), so now we accept any row with at least one classification field.
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import concurrent.futures
import json
import os
import re
import subprocess
import time
from pathlib import Path

import bse_headers as BH  # §181 BSE headers

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "scripts" / "stock_data.json"
BSE_JSON = "/tmp/bse.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

bse = json.load(open(BSE_JSON))
scrip_list = []
for b in bse:
    if b.get("Status") != "Active" or b.get("Segment") != "Equity":
        continue
    code = (b.get("SCRIP_CD") or "").strip()
    sid = (b.get("scrip_id") or "").strip()
    name = (b.get("Scrip_Name") or "").strip()
    if not code:
        continue
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    referer = f"https://www.bseindia.com/stock-share-price/{slug}/{sid.lower()}/{code}/"
    scrip_list.append((code, sid, referer))
print(f"BSE scrips to enrich: {len(scrip_list)}")


def fetch(entry):
    code, _sid, _ref = entry
    url = f"https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w?quotetype=EQ&scripcode={code}"
    try:
        r = subprocess.run(
            # honest UA; CURL_ARGS already carries Accept + Referer — a SECOND Referer is a 403 (§181, §190:
            # this call still sent its per-scrip Referer, and got 0/4,926 on the last run)
            ["curl", "-s", "--max-time", "8", "-A", BH.UA, *BH.CURL_ARGS, url],
            capture_output=True,
            timeout=10,
        )
        d = json.loads(r.stdout)
        # Accept the row if ANY classification field is non-empty
        sector = (d.get("Sector") or "").strip()
        industry_new = (d.get("IndustryNew") or "").strip()
        igroup = (d.get("IGroup") or "").strip()
        industry_old = (d.get("Industry") or "").strip()
        isub = (d.get("ISubGroup") or "").strip()
        if sector or industry_new or igroup or industry_old:
            return code, {
                "sector": sector,
                "industry": industry_new or igroup or industry_old or sector,
                "igroup": igroup or "",
                "subgroup": isub or "",
            }
    except Exception:
        pass
    return code, None


# Up to 4 passes — BSE's endpoint is flaky from cloud IPs, retries pay off.
sectors = {}
PASSES = (
    0 if os.environ.get("FETCH_SECTORS_DRY") else 4
)  # DRY = no BSE traffic, resolution logic only (prints per-ticker codes)
for attempt in range(PASSES):
    todo = [s for s in scrip_list if s[0] not in sectors]
    if not todo:
        break
    print(f"Pass {attempt + 1}/{PASSES}: {len(todo)} scrips")
    t0 = time.time()
    # Smaller worker pool on later passes — BSE chokes if hammered too hard
    workers = 12 if attempt < 2 else 6
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for code, info in ex.map(fetch, todo):
            if info:
                sectors[code] = info
    print(
        f"  recovered {len(sectors)} cumulative, +{sum(1 for c in todo if c[0] in sectors)} this pass, {time.time() - t0:.0f}s"
    )
    if attempt < PASSES - 1 and len(todo) - sum(1 for c in todo if c[0] in sectors) > 50:
        time.sleep(5)  # cool-off if BSE was rate-limiting

print(f"\nTotal sector rows: {len(sectors)} / {len(scrip_list)} ({100 * len(sectors) / len(scrip_list):.1f}%)")

# --- Fallback: the last PUBLISHED build's labels, fill-only (DATA_RUNBOOK §150) ------------
# 2026-09-23: api.bseindia.com answered 403 "Access Denied" to every client for hours. With
# `sectors` empty, the merge below stamped EVERY stock "Uncategorized" — so a run that survives
# the outage (the scrip-master fallback in refresh.yml) would have shipped a sector-less site.
# Any ticker BSE did not answer for THIS run keeps the sector/industry it shipped with last time;
# a fresh answer always wins. docs/stock_data.bin is the build that is live right now (committed
# by the previous successful run) — the same "last-good copy" the scrip master falls back to.
PREV = {}
try:
    import gzip

    with open(ROOT / "docs" / "stock_data.bin", "rb") as fh:
        for _t, _m in (json.loads(gzip.decompress(fh.read())).get("meta") or {}).items():
            if _m.get("sector") and _m["sector"] not in ("Uncategorized", "NSE-SME"):
                PREV[_t] = {"sector": _m["sector"], "industry": _m.get("industry") or ""}
except Exception as e:
    print(f"previous build unreadable, no sector fallback this run: {e}")
print(f"Previous build carries sector labels for {len(PREV)} tickers (fallback for any BSE did not answer)")

# Histogram of industries we found
from collections import Counter

ind_hist = Counter(v.get("industry") for v in sectors.values() if v.get("industry"))
print("Top industries:")
for ind, n in ind_hist.most_common(15):
    print(f"  {n:5d}  {ind}")

# --- Merge into stock_data.json --------------------------------------
# Build TWO lookups: scrip_id -> code (text match) and ISIN -> code (canonical).
# Many NSE symbols differ slightly from BSE scrip_id but share an ISIN, so the
# ISIN fallback recovers ~50% more sector matches.
data = json.loads(DATA.read_text())
sid_to_code = {}
isin_to_code = {}
for b in bse:
    sid = (b.get("scrip_id") or "").strip()
    code = (b.get("SCRIP_CD") or "").strip()
    isin = (b.get("ISIN_NUMBER") or "").strip()
    if sid and code:
        sid_to_code[sid] = code
    if isin and code:
        isin_to_code[isin] = code
code_to_isin = {c: i for i, c in isin_to_code.items()}

# Build NSE symbol -> ISIN map from the NSE master
import csv

nse_sym_to_isin = {}
with open("/tmp/nse.csv") as f:
    for row in csv.DictReader(f):
        row = {k.strip(): (v or "").strip() for k, v in row.items()}
        sym = row.get("SYMBOL")
        isin = row.get("ISIN NUMBER")
        if sym and isin:
            nse_sym_to_isin[sym] = isin
print(f"NSE symbol->ISIN map: {len(nse_sym_to_isin)}")

merged = 0
carried = 0  # §150: kept from the previous build because BSE gave no answer this run
fallback_isin = 0
fallback_sid = 0
refused_sid = 0  # §76: scrip_id twin with a different ISIN, not used
sme_rows = 0  # NSE-SME rows kept out of the BSE lookup
for ticker, meta in data["meta"].items():
    sym, suffix = ticker.rsplit(".", 1)
    code = None
    if suffix == "BO":
        # Ticker can be {numeric_code}.BO OR {scrip_id_text}.BO depending on
        # which one Yahoo accepted. Detect numeric vs text.
        if sym.isdigit():
            code = sym
        else:
            code = sid_to_code.get(sym)
            if code:
                fallback_sid += 1
    elif meta.get("sme"):
        # NSE SME platform (Emerge) listing: not on BSE at all (measured 2026-09-22: 0 of 571 SME
        # ISINs on BSE), and 5 SME symbols COLLIDE with unrelated BSE scrip_ids (RAJPUTANA, MAL,
        # SEL, ZEAL, GSTL) — a scrip_id lookup here would hand them another company's industry
        # (DATA_RUNBOOK §76 / §145). No BSE lookup; the group is set below.
        code = None
    else:  # .NS
        # NSE symbol: direct scrip_id match, ISIN-GATED (§76: a scrip_id equal to the NSE symbol is
        # a coincidence until the ISIN agrees — BSE "KALYANI" is Kalyani Cast-Tech, NSE KALYANI is
        # Kalyani Commercials; same for FOCUS), then ISIN fallback.
        code = sid_to_code.get(sym)
        isin = nse_sym_to_isin.get(sym)
        if code and isin and code_to_isin.get(code) and code_to_isin[code] != isin:
            refused_sid += 1
            code = None
        if not code and isin:
            code = isin_to_code.get(isin)
            if code:
                fallback_isin += 1
    if PASSES == 0:
        print(f"  DRY resolve {ticker}: code={code}")
    info = sectors.get(code or "")
    if info:
        meta["sector"] = info.get("sector") or info.get("industry") or "Uncategorized"
        meta["industry"] = info.get("industry") or info.get("igroup") or info.get("sector") or ""
        merged += 1
    elif meta.get("sme"):
        meta["sector"] = "NSE-SME"  # the dashboard's industry filter groups these as "NSE-SME (n)"
        meta["industry"] = ""
        sme_rows += 1
    elif ticker in PREV:
        meta["sector"], meta["industry"] = PREV[ticker]["sector"], PREV[ticker]["industry"]
        carried += 1
    else:
        meta["sector"] = "Uncategorized"
        meta["industry"] = ""

DATA.write_text(json.dumps(data, separators=(",", ":")))
print(f"\nMerged sector data into {merged}/{len(data['meta'])} stocks ({100 * merged / len(data['meta']):.1f}%)")
print(f"  via numeric/scrip_id direct: {merged - fallback_isin - fallback_sid}")
print(f"  via .BO scrip_id text match: {fallback_sid}")
print(f"  via ISIN fallback:           {fallback_isin}")
print(f"  scrip_id twins refused (ISIN differs, §76): {refused_sid}")
print(f"  NSE-SME rows (no BSE lookup, sector NSE-SME): {sme_rows}")
print(f"  carried from the previous build (BSE gave no answer this run, §150): {carried}")
if (
    carried > 50
):  # the script's own "BSE is rate-limiting" threshold — a handful of flaky scrips is normal, this is an outage
    print(
        f"::warning::fetch_sectors: {carried} tickers keep the previous build's sector/industry — BSE ComHeadernew answered for {len(sectors)}/{len(scrip_list)} scrips this run (DATA_RUNBOOK §150)"
    )
print(f"Updated {DATA}")
