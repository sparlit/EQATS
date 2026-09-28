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
"""Fetch historical price data for the full NSE+BSE universe via curl.

History ranges back to **1 Jan 1996** (Yahoo Finance's earliest reliable data
for Indian equities). To keep the dashboard payload small, we use:

  * Weekly closes from 1996-01-01 to 2019-12-31  (~1,250 points / stock)
  * Daily closes  from 2020-01-01 to today        (~1,500 points / stock)

Both ranges are concatenated (sorted, deduped by timestamp) into one series.

Recovery passes: each entry has a primary ticker (NSE if symbol exists in NSE
master, else BSE) and one or two alternate tickers. We try them in order; if
all fail, the stock still ships in the dashboard with empty series so the row
shows up with metadata + "—" prices.
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import concurrent.futures
import csv
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import bse_headers as BH  # §181 BSE headers
import bse_names as BN  # §204: BSE's "-$" scrip-name marker never reaches a published name

# Filter out non-stock instruments (ETFs, mutual fund schemes, REITs, InvITs).
# Word-boundary regex so we don't false-positive on companies like
# "Brainbees Solutions" or "Capital Trust" that just contain ETF-adjacent
# substrings as part of larger words.
NONSTOCK_RE = re.compile(
    r"\b(?:ETF|BeES|InvIT|REIT|Index Fund|Exchange Traded Fund|FoF)\b"
    r"|Mutual Fund",
    re.IGNORECASE,
)


def is_non_stock(name, isin=""):
    # ISINs starting "INF" are mutual-fund / ETF UNITS by construction (NSDL assigns INF to fund
    # schemes) — the name regex missed e.g. INFRA ("Mirae Asset Nifty India Infrastructure &
    # Logistics") and 56 Nippon segregated-portfolio units on BSE (measured 2026-09-23, §145).
    return (bool(name) and bool(NONSTOCK_RE.search(name))) or str(isin or "").upper().startswith("INF")


ROOT = Path(__file__).resolve().parent.parent
NSE_CSV = "/tmp/nse.csv"  # NSE main-board equity master (EQUITY_L.csv)
NSE_SME_CSV = "/tmp/nse_sme.csv"  # NSE SME-platform master (emerge/.../SME_EQUITY_L.csv) — optional
BSE_JSON = "/tmp/bse.json"
OUT_JSON = ROOT / "scripts" / "stock_data.json"

# --- Build universe ----------------------------------------------------
# NSE main board: EVERY cash-segment equity series — EQ (rolling), BE (trade-for-trade) and BZ
# (trade-for-trade + surveillance). All three are ordinary listed companies trading every session
# (DATA_RUNBOOK §80); until 2026-09-22 only EQ was read here, which dropped the 27 BE/BZ names that
# BSE does not list (ABMINTLLTD, DPSCLTD, KOTARISUG, ...). A rights entitlement rides the same file
# for a few weeks as `<SYMBOL>-RE` in series BE and is not a stock -> excluded.
NSE_SERIES = ("EQ", "BE", "BZ")
nse_main = {}  # symbol -> {"name", "isin", "series"}
with open(NSE_CSV) as f:
    for row in csv.DictReader(f):
        row = {k.strip(): (v or "").strip() for k, v in row.items()}
        sym = row.get("SYMBOL")
        if not sym or row.get("SERIES") not in NSE_SERIES or sym.endswith("-RE"):
            continue
        nse_main[sym] = {
            "name": row.get("NAME OF COMPANY") or sym,
            "isin": row.get("ISIN NUMBER") or "",
            "series": row["SERIES"],
        }
nse_symbols = set(nse_main)
print(f"NSE main-board symbols (EQ/BE/BZ, rights entitlements excluded): {len(nse_symbols)}")

# NSE SME platform (Emerge): series SM (rolling) / ST (trade-for-trade) / SZ (surveillance), in a
# SEPARATE master. Never joined to a BSE scrip by scrip_id: measured 2026-09-22, 0 of 571 SME ISINs
# are on BSE while 5 SME symbols collide with UNRELATED BSE scrip_ids (RAJPUTANA, MAL, SEL, ZEAL,
# GSTL — the §76 coincidence class). Yahoo carries almost none of these tickers (SUNLITE.NS = Not
# Found; the few it has are typed MUTUALFUND and rejected below), so their series come from the
# NSE bhavcopy store via fill_prices_from_sf.py right after this script. DATA_RUNBOOK §145.
nse_sme = {}
if os.path.exists(NSE_SME_CSV):
    with open(NSE_SME_CSV) as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            sym = row.get("SYMBOL")
            if not sym or row.get("SERIES") not in ("SM", "ST", "SZ") or sym.endswith("-RE"):
                continue  # -RE = rights entitlement, not a stock
            nse_sme[sym] = {
                "name": row.get("NAME_OF_COMPANY") or sym,
                "isin": row.get("ISIN_NUMBER") or "",
                "series": row["SERIES"],
            }
    print(f"NSE SME symbols (SM/ST/SZ): {len(nse_sme)}")
else:
    print(f"WARN {NSE_SME_CSV} missing — no SME rows in this build")

bse_scrips = json.load(open(BSE_JSON))
universe, seen, skipped_etf, twin_other_co = [], set(), 0, set()
for b in bse_scrips:
    if b.get("Status") != "Active" or b.get("Segment") != "Equity":
        continue
    sid = (b.get("scrip_id") or "").strip()
    code = (b.get("SCRIP_CD") or "").strip()
    name = BN.clean_scrip_name(b.get("Scrip_Name"))  # BSE alternates "UNO Minda Ltd-$" / "UNO Minda Ltd" (§204)
    isin = (b.get("ISIN_NUMBER") or "").strip()
    try:
        mcap = float(b.get("Mktcap") or 0)
    except:
        mcap = 0
    grp = (b.get("GROUP") or "").strip() or "Other"
    if not sid and not code:
        continue
    if is_non_stock(name, isin):
        skipped_etf += 1
        continue
    # §76: a BSE scrip_id equal to an NSE symbol is a COINCIDENCE until the ISIN agrees. Both ISINs
    # known and different = two companies (measured 2026-09-22: BSE "KALYANI" = Kalyani Cast-Tech,
    # NSE KALYANI = Kalyani Commercials; same for FOCUS) -> the BSE row stays .BO and never falls
    # back to that .NS ticker, and the NSE symbol ships on its own below. Either ISIN blank = the
    # coincidence cannot be disproved here, so the long-standing scrip_id join stands.
    n_isin = nse_main[sid]["isin"] if sid in nse_symbols else None
    other_co = bool(sid in nse_symbols and isin and n_isin and isin != n_isin)
    if other_co:
        twin_other_co.add(sid)
    if sid and sid in nse_symbols and not other_co:
        primary = f"{sid}.NS"
        alts = [f"{sid}.BO"] + ([f"{code}.BO"] if code else [])
        display = sid
        key = ("NS", sid)
    else:
        primary = f"{code}.BO" if code else f"{sid}.BO"
        alts = ([f"{sid}.BO"] if sid and code else []) + ([f"{sid}.NS"] if sid and not other_co else [])
        display = sid or code
        key = ("BO", code or sid)
    if key in seen:
        continue
    seen.add(key)
    universe.append(
        {
            "primary": primary,
            "alts": alts,
            "display": display,
            "name": name,
            "group": grp,
            "mcap": round(mcap, 2),
        }
    )

bse_nse_syms = {u["display"] for u in universe if u["primary"].endswith(".NS")}
for sym in sorted(nse_symbols - bse_nse_syms):
    info = nse_main[sym]
    if is_non_stock(info["name"], info["isin"]):
        skipped_etf += 1
        continue
    universe.append(
        {
            "primary": f"{sym}.NS",
            "alts": ([] if sym in twin_other_co else [f"{sym}.BO"]),
            "display": sym,
            "name": info["name"],
            "group": "NSE-only",
            "mcap": 0,
        }
    )
n_sme = 0
for sym in sorted(nse_sme):
    if sym in bse_nse_syms:
        continue  # cannot happen today (0 SME ISINs on BSE) — guard anyway
    info = nse_sme[sym]
    if is_non_stock(info["name"], info["isin"]):
        skipped_etf += 1
        continue
    universe.append(
        {
            "primary": f"{sym}.NS",
            "alts": [],  # no BSE twin: a `.BO` alt would be a §76 coincidence
            "display": sym,
            "name": info["name"],
            "group": "NSE-SME",
            "mcap": 0,
            "sme": True,
        }
    )
    n_sme += 1

print(f"Skipped non-stocks (ETFs/MF/REITs/InvITs): {skipped_etf}")
print(
    f"Total universe: {len(universe)}  (NSE-SME rows: {n_sme}; BSE scrip_ids refused as another company: {sorted(twin_other_co)})"
)
if os.environ.get("FETCH_ALL_DRY"):
    # universe-only smoke run (no Yahoo traffic): counts by group, then stop
    from collections import Counter

    print("DRY RUN — groups:", dict(Counter(u["group"] for u in universe).most_common(12)))
    sys.exit(0)

# --- Date ranges -------------------------------------------------------
END_TS = int(time.time())
WEEKLY_START_TS = int(_dt.datetime(1996, 1, 1).timestamp())
DAILY_START_TS = int(_dt.datetime(2020, 1, 1).timestamp())
START_TS = WEEKLY_START_TS  # this is what we tell the dashboard

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
NEW_LISTING_MAX_AGE_S = 7 * 86400  # a one-bar series is a listing-day stock only if that bar is this recent


def fetch_chart(ticker, p1, p2, interval):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval={interval}"
    try:
        res = subprocess.run(
            ["curl", "-s", "--max-time", "12", "-A", UA, *BH.CURL_ARGS, url], capture_output=True, timeout=15
        )
        body = res.stdout
        if not body:
            return None
        data = json.loads(body)
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        result = result[0]
        # Yahoo sometimes mis-classifies BSE scrips as MUTUALFUND; reject those
        if result.get("meta", {}).get("instrumentType") and result["meta"]["instrumentType"] != "EQUITY":
            return None
        ts = result.get("timestamp") or []
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        return [[t2, round(c, 2)] for t2, c in zip(ts, closes, strict=False) if c is not None]
    except Exception:
        return None


def fetch_with_fallback(entry):
    """Try primary then alts. For each candidate, fetch weekly+daily, merge, dedupe."""
    for ticker in [entry["primary"]] + entry["alts"]:
        weekly = fetch_chart(ticker, WEEKLY_START_TS, DAILY_START_TS - 1, "1wk")
        daily = fetch_chart(ticker, DAILY_START_TS, END_TS, "1d")
        combined = (weekly or []) + (daily or [])
        if not combined:
            continue
        # Sort + dedupe by ts
        seen, out = set(), []
        for ts, close in sorted(combined, key=lambda x: x[0]):
            if ts in seen:
                continue
            seen.add(ts)
            out.append([ts, close])
        if len(out) >= 2:
            return ticker, out
        # A stock on its LISTING DAY has exactly one bar. Dropping it left new listings blank for their
        # whole first session (HEROMOTORS / SSRETAIL / JSIPL, 23-Sep-2026, §145); the page shows such a
        # row as "Day 1". A lone bar is kept only when it is recent — an old single stray bar is not a
        # listing, and falling through to the alternates stays the rule for those.
        if len(out) == 1 and END_TS - out[0][0] <= NEW_LISTING_MAX_AGE_S:
            return ticker, out
    return entry["primary"], None


# --- Fetch the universe ------------------------------------------------
results = {}
empty = {}
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
    futures = {ex.submit(fetch_with_fallback, u): u for u in universe}
    done = 0
    for fut in concurrent.futures.as_completed(futures):
        done += 1
        entry = futures[fut]
        winning_ticker, pairs = fut.result()
        entry["ticker"] = winning_ticker
        if pairs is not None:
            results[winning_ticker] = pairs
        else:
            empty[winning_ticker] = None
        if done % 250 == 0:
            ok = 100 * len(results) / done
            print(
                f"  {done}/{len(universe)}  with_data={len(results)} ({ok:.0f}%)  empty={len(empty)}  elapsed={time.time() - start:.0f}s",
                flush=True,
            )

elapsed = time.time() - start
print(f"\nDone: {len(results)} with data, {len(empty)} without, total {len(universe)} ({elapsed:.0f}s)")

universe.sort(key=lambda u: -u["mcap"])

payload = {
    "generatedAt": END_TS,
    "startTs": START_TS,
    "endTs": END_TS,
    "dailyStartTs": DAILY_START_TS,
    "meta": {
        u["ticker"]: {
            "symbol": u["display"],
            "name": u["name"],
            "sector": u["group"],
            "mcap": u["mcap"],
            **({"sme": True} if u.get("sme") else {}),  # NSE SME platform listing (runbook §145)
        }
        for u in universe
    },
    "series": results,
}
OUT_JSON.write_text(json.dumps(payload, separators=(",", ":")))
print(f"Wrote {OUT_JSON} ({OUT_JSON.stat().st_size / 1024 / 1024:.2f} MB)")
print(f"Universe in dashboard: {len(payload['meta'])} stocks")
print(f"  with price history:  {len(payload['series'])}")
print(f"  metadata-only:       {len(payload['meta']) - len(payload['series'])}")
