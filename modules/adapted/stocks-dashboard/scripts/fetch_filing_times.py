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


#!/usr/bin/env python
"""Fetch BSE result-filing broadcast TIMES for every month-end trading day that
carries a fundamentals filing, so the backtest can apply a precise 15:30 IST
availability gate (a result filed after the 15:30 close on a rebalance day must
NOT be treated as available that day). See memory project-stocks-1530-gate.

Strategy: query BSE AnnSubCategoryGetData per-DATE (all Result announcements that
day, ~50/page) instead of per-stock. There are only ~80 distinct month-end dates
with filings, so this is ~300 requests, not ~3,800.

Output: scripts/_filing_times.json = { "YYYYMMDD": { "<scripcode>": ["ISO_ts", ...] } }
Resumable: skips dates already present. Run again to fill any that failed.
"""
import gzip
import http.cookiejar
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _req(u, ref="https://www.bseindia.com/corporates/ann.html"):
    return urllib.request.Request(
        u, headers={"User-Agent": UA, "Accept": "*/*", "Referer": ref, "Origin": "https://www.bseindia.com"}
    )


op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
op.open(_req("https://www.bseindia.com/"), timeout=30).read()


def get(u):
    r = op.open(_req(u), timeout=70)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def fetch_date(dstr):
    """All Result announcements broadcast on YYYYMMDD -> {scripcode(str): [NEWS_DT,...]}."""
    out = {}
    page = 1
    total = None
    while True:
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
            f"pageno={page}&strCat=Result&strPrevDate={dstr}&strToDate={dstr}"
            "&strScrip=&strSearch=P&strType=C&subcategory=-1"
        )
        for attempt in range(4):
            try:
                j = json.loads(get(u))
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        tbl = j.get("Table", []) or []
        if total is None:
            t1 = j.get("Table1", [])
            total = (t1[0].get("ROWCNT") if t1 else 0) or 0
        for t in tbl:
            sc = t.get("SCRIP_CD")
            nd = t.get("NEWS_DT")
            if sc is None or not nd:
                continue
            out.setdefault(str(sc), []).append(nd)
        got = page * 50
        if not tbl or got >= total:
            break
        page += 1
        time.sleep(0.4)
    return out


def main():
    dates = [str(x) for x in json.load(open(os.path.join(HERE, "_gate_dates.json")))]
    path = os.path.join(HERE, "_filing_times.json")
    store = json.load(open(path)) if os.path.exists(path) else {}
    todo = [d for d in dates if d not in store]
    print(f"{len(dates)} dates total, {len(todo)} to fetch", flush=True)
    for i, d in enumerate(todo):
        try:
            store[d] = fetch_date(d)
            print(f"[{i + 1}/{len(todo)}] {d}: {len(store[d])} scrips", flush=True)
        except Exception as e:
            print(f"[{i + 1}/{len(todo)}] {d}: FAILED {e}", flush=True)
        # persist after each date so a crash is resumable
        json.dump(store, open(path, "w"), separators=(",", ":"))
        time.sleep(0.3)
    print("done; total dates stored:", len(store), flush=True)


if __name__ == "__main__":
    main()
