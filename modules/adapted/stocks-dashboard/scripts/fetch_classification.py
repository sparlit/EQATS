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
"""Fetch the FULL 5-level BSE industry classification for the dashboard universe.

`fetch_sectors.py` already pulls BSE's `ComHeadernew/w` per scrip but keeps only
the two coarsest levels (Sector + IndustryNew). BSE actually returns FIVE levels
of decreasing granularity, e.g. for Reliance (500325):

    Sector      -> "Energy"                      (L1 macro,  ~14 values)
    IndustryNew -> "Oil, Gas & Consumable Fuels" (L2 sector, ~24 values)
    IGroup      -> "Petroleum Products"          (L3 group,  ~60 values)
    Industry    -> "Refineries & Marketing"      (L4 basic,  ~190 values)  <- the "Heat Exchangers" level
    ISubGroup   -> "Refineries & Marketing"      (L5 sub,    ~190 values)

This script captures ALL five and writes docs/sector_classification.json keyed by
the SAME ticker as docs/stock_data.bin's meta (e.g. "RELIANCE.NS", "500325.BO"),
so the Sector-Index browser can group stocks at any level without touching the
central stock_data.bin pipeline. Additive + isolated by design.
"""
import concurrent.futures
import csv
import gzip
import json
import os
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "sector_classification.json"
TMP = tempfile.gettempdir()
NSE_CSV = os.path.join(TMP, "nse_eql.csv")
BSE_JSON = os.path.join(TMP, "bse_scrips.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# --- 0. download the scrip masters (same URLs/headers as .github/workflows/refresh.yml) ---
def dl(url, out, extra_headers=()):
    for _attempt in range(3):
        cmd = ["curl", "-s", "--max-time", "40", "-A", UA]
        for h in extra_headers:
            cmd += ["-H", h]
        cmd += [url, "-o", out]
        subprocess.run(cmd, timeout=60)
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            return True
        time.sleep(2)
    return False


if not (os.path.exists(NSE_CSV) and os.path.getsize(NSE_CSV) > 1000):
    print("Downloading NSE EQUITY_L.csv ...", flush=True)
    dl("https://archives.nseindia.com/content/equities/EQUITY_L.csv", NSE_CSV)
if not (os.path.exists(BSE_JSON) and os.path.getsize(BSE_JSON) > 1000):
    print("Downloading BSE ListofScripData ...", flush=True)
    dl(
        "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
        BSE_JSON,
        ["Referer: https://www.bseindia.com/"],
    )
print(f"NSE master: {os.path.getsize(NSE_CSV)} bytes | BSE master: {os.path.getsize(BSE_JSON)} bytes", flush=True)

bse = json.load(open(BSE_JSON, encoding="utf-8"))

# --- 1. mapping tables: scrip_id->code, ISIN->code, NSE symbol->ISIN ---
sid_to_code, isin_to_code = {}, {}
for b in bse:
    sid = (b.get("scrip_id") or "").strip()
    code = (b.get("SCRIP_CD") or "").strip()
    isin = (b.get("ISIN_NUMBER") or "").strip()
    if sid and code:
        sid_to_code[sid] = code
    if isin and code:
        isin_to_code[isin] = code

nse_sym_to_isin = {}
with open(NSE_CSV, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row = {k.strip(): (v or "").strip() for k, v in row.items()}
        if row.get("SYMBOL") and row.get("ISIN NUMBER"):
            nse_sym_to_isin[row["SYMBOL"]] = row["ISIN NUMBER"]
print(
    f"maps: sid->code {len(sid_to_code)}, isin->code {len(isin_to_code)}, nseSym->isin {len(nse_sym_to_isin)}",
    flush=True,
)

# --- 2. resolve every dashboard ticker -> BSE scrip code ---
SD = json.loads(gzip.decompress((ROOT / "docs" / "stock_data.bin").read_bytes()))
META = SD["meta"]
ticker_code = {}  # ticker -> code
for ticker in META:
    sym, suffix = ticker.rsplit(".", 1)
    code = None
    if suffix == "BO":
        code = sym if sym.isdigit() else sid_to_code.get(sym)
    else:  # .NS
        code = sid_to_code.get(sym)
        if not code:
            isin = nse_sym_to_isin.get(sym)
            if isin:
                code = isin_to_code.get(isin)
    if code:
        ticker_code[ticker] = code
codes_needed = sorted(set(ticker_code.values()))
print(
    f"tickers {len(META)} -> resolved to {len(ticker_code)} tickers across {len(codes_needed)} unique BSE codes",
    flush=True,
)


# --- 3. fetch ComHeadernew per code (threaded, retry passes) ---
def fetch(code):
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
                "Referer: https://www.bseindia.com/",
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
        macro = (d.get("Sector") or "").strip()
        sector = (d.get("IndustryNew") or "").strip()
        igroup = (d.get("IGroup") or "").strip()
        industry = (d.get("Industry") or "").strip()
        subgroup = (d.get("ISubGroup") or "").strip()
        if macro or sector or igroup or industry:
            return code, {
                "macro": macro,
                "sector": sector,
                "igroup": igroup,
                "industry": industry,
                "subgroup": subgroup,
            }
    except Exception:
        pass
    return code, None


cls = {}
PASSES = 4
for attempt in range(PASSES):
    todo = [c for c in codes_needed if c not in cls]
    if not todo:
        break
    workers = 12 if attempt < 2 else 6
    t0 = time.time()
    print(f"Pass {attempt + 1}/{PASSES}: fetching {len(todo)} codes ({workers} workers)", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for code, info in ex.map(fetch, todo):
            if info:
                cls[code] = info
    got = sum(1 for c in todo if c in cls)
    print(f"  cumulative {len(cls)}/{len(codes_needed)} (+{got} this pass) in {time.time() - t0:.0f}s", flush=True)
    miss = len(todo) - got
    if attempt < PASSES - 1 and miss > 50:
        time.sleep(5)

# --- 4. key by ticker; write side file ---
out = {}
for ticker, code in ticker_code.items():
    info = cls.get(code)
    if info:
        out[ticker] = info

# Safety: a flaky BSE day (esp. from a cloud IP) can return mostly nulls. Never
# clobber a good committed file with a partial one — bail if coverage collapsed.
MIN_OK = 3000
if len(out) < MIN_OK and OUT.exists():
    print(
        f"\n⚠️  ONLY {len(out)} classified (< {MIN_OK}); BSE likely rate-limited. "
        f"KEEPING existing {OUT.name}, not overwriting.",
        flush=True,
    )
    raise SystemExit(0)

OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print(f"\nWrote {OUT}  ({len(out)} tickers classified, {OUT.stat().st_size / 1024:.0f} KB)", flush=True)

# --- 5. report level distributions (so we can choose grouping granularity) ---
for lvl in ["macro", "sector", "igroup", "industry", "subgroup"]:
    vals = Counter(v[lvl] for v in out.values() if v.get(lvl))
    print(f"\n=== {lvl}: {len(vals)} distinct (non-empty {sum(vals.values())}) ===", flush=True)
    for name, n in vals.most_common(12):
        print(f"  {n:5d}  {name}", flush=True)
print("\nDONE.", flush=True)
