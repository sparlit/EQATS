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
import concurrent.futures
import csv
import datetime as _dt
import json
import re
import subprocess
import time
from pathlib import Path

# Filter out non-stock instruments (ETFs, mutual fund schemes, REITs, InvITs).
# Word-boundary regex so we don't false-positive on companies like
# "Brainbees Solutions" or "Capital Trust" that just contain ETF-adjacent
# substrings as part of larger words.
NONSTOCK_RE = re.compile(
    r"\b(?:ETF|BeES|InvIT|REIT|Index Fund|Exchange Traded Fund|FoF)\b"
    r"|Mutual Fund",
    re.IGNORECASE,
)


def is_non_stock(name):
    return bool(name) and bool(NONSTOCK_RE.search(name))


ROOT = Path(__file__).resolve().parent.parent
NSE_CSV = "/tmp/nse.csv"
BSE_JSON = "/tmp/bse.json"
OUT_JSON = ROOT / "scripts" / "stock_data.json"

# --- Build universe ----------------------------------------------------
nse_symbols = set()
with open(NSE_CSV) as f:
    for row in csv.DictReader(f):
        row = {k.strip(): (v or "").strip() for k, v in row.items()}
        if row.get("SERIES") == "EQ" and row.get("SYMBOL"):
            nse_symbols.add(row["SYMBOL"])
print(f"NSE EQ symbols: {len(nse_symbols)}")

bse_scrips = json.load(open(BSE_JSON))
universe, seen, skipped_etf = [], set(), 0
for b in bse_scrips:
    if b.get("Status") != "Active" or b.get("Segment") != "Equity":
        continue
    sid = (b.get("scrip_id") or "").strip()
    code = (b.get("SCRIP_CD") or "").strip()
    name = (b.get("Scrip_Name") or "").strip()
    try:
        mcap = float(b.get("Mktcap") or 0)
    except:
        mcap = 0
    grp = (b.get("GROUP") or "").strip() or "Other"
    if not sid and not code:
        continue
    if is_non_stock(name):
        skipped_etf += 1
        continue
    if sid and sid in nse_symbols:
        primary = f"{sid}.NS"
        alts = [f"{sid}.BO"] + ([f"{code}.BO"] if code else [])
        display = sid
        key = ("NS", sid)
    else:
        primary = f"{code}.BO" if code else f"{sid}.BO"
        alts = ([f"{sid}.BO"] if sid and code else []) + ([f"{sid}.NS"] if sid else [])
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
    universe.append(
        {
            "primary": f"{sym}.NS",
            "alts": [f"{sym}.BO"],
            "display": sym,
            "name": sym,
            "group": "NSE-only",
            "mcap": 0,
        }
    )

print(f"Skipped non-stocks (ETFs/MF/REITs/InvITs): {skipped_etf}")
print(f"Total universe: {len(universe)}")

# --- Date ranges -------------------------------------------------------
END_TS = int(time.time())
WEEKLY_START_TS = int(_dt.datetime(1996, 1, 1).timestamp())
DAILY_START_TS = int(_dt.datetime(2020, 1, 1).timestamp())
START_TS = WEEKLY_START_TS  # this is what we tell the dashboard

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_chart(ticker, p1, p2, interval):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval={interval}"
    try:
        res = subprocess.run(["curl", "-s", "--max-time", "12", "-A", UA, url], capture_output=True, timeout=15)
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
