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
import concurrent.futures
import json
import re
import subprocess
import time
from pathlib import Path

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
    code, _sid, ref = entry
    url = f"https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w?quotetype=EQ&scripcode={code}"
    try:
        r = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "8",
                "-A",
                UA,
                "-H",
                f"Referer: {ref}",
                "-H",
                "Origin: https://www.bseindia.com",
                "-H",
                "Accept: application/json, text/plain, */*",
                url,
            ],
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
PASSES = 4
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
fallback_isin = 0
fallback_sid = 0
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
    else:  # .NS
        # NSE symbol: try direct scrip_id match, then ISIN fallback.
        code = sid_to_code.get(sym)
        if not code:
            isin = nse_sym_to_isin.get(sym)
            if isin:
                code = isin_to_code.get(isin)
                if code:
                    fallback_isin += 1
    info = sectors.get(code or "")
    if info:
        meta["sector"] = info.get("sector") or info.get("industry") or "Uncategorized"
        meta["industry"] = info.get("industry") or info.get("igroup") or info.get("sector") or ""
        merged += 1
    else:
        meta["sector"] = "Uncategorized"
        meta["industry"] = ""

DATA.write_text(json.dumps(data, separators=(",", ":")))
print(f"\nMerged sector data into {merged}/{len(data['meta'])} stocks ({100 * merged / len(data['meta']):.1f}%)")
print(f"  via numeric/scrip_id direct: {merged - fallback_isin - fallback_sid}")
print(f"  via .BO scrip_id text match: {fallback_sid}")
print(f"  via ISIN fallback:           {fallback_isin}")
print(f"Updated {DATA}")
