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
"""Harvest BSE's corporate-announcement index for a set of scrip codes over 2001-10..2006-03 (runbook §129).
Usage: python3 scripts/bse_ann_harvest.py --codes <sym->[how,code,...] json> --cache <dir>
"""
# Harvest BSE's announcement index (AnnSubCategoryGetData, strCat=-1) for every code-resolved 2002-04 residue
# symbol over 2001-10-01 .. 2006-03-31 in 6-month windows, paginated (50 rows/page). Cached per (code, window).
# §55a: an EMPTY Table is often rate-limiting, not absence -> retry on a fresh session before recording 'empty'.
import collections
import json
import os
import sys
import time

import requests

S = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(S, "cache")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
H = {"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Accept": "application/json, text/plain, */*"}
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--codes", required=True)
ap.add_argument("--cache", required=True)
A = ap.parse_args()
CACHE = A.cache
os.makedirs(CACHE, exist_ok=True)
codes = json.load(open(A.codes))
WINDOWS = [
    ("20011001", "20020331"),
    ("20020401", "20020930"),
    ("20021001", "20030331"),
    ("20030401", "20030930"),
    ("20031001", "20040331"),
    ("20040401", "20040930"),
    ("20041001", "20050331"),
    ("20050401", "20050930"),
    ("20051001", "20060331"),
]
sess = requests.Session()
sess.headers.update(H)


def get(url):
    global sess
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=60)
            if r.status_code == 200:
                d = r.json()
                return d.get("Table") or [], None
            err = "http%d" % r.status_code
        except Exception as e:
            err = type(e).__name__
        time.sleep(4 * (attempt + 1))
        sess = requests.Session()
        sess.headers.update(H)
    return None, err


def window(code, F, T):
    p = os.path.join(CACHE, f"{code}_{F}_{T}.json")
    if os.path.exists(p):
        return json.load(open(p)), True
    rows = []
    page = 1
    err = None
    while page <= 6:
        tab, err = get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1&strPrevDate=%s&strToDate=%s&strScrip=%s&strSearch=P&strType=C&subcategory=-1"
            % (page, F, T, code)
        )
        if tab is None:
            break
        if not tab and page == 1:
            # §55a empty-table check: retry once on a fresh session after a pause
            time.sleep(5)
            globals()["sess"] = requests.Session()
            globals()["sess"].headers.update(H)
            tab, err = get(
                f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate={F}&strToDate={T}&strScrip={code}&strSearch=P&strType=C&subcategory=-1"
            )
            if tab is None:
                break
        rows += tab
        if len(tab) < 50:
            break
        page += 1
        time.sleep(0.6)
    rec = {
        "code": code,
        "from": F,
        "to": T,
        "rows": rows,
        "err": err,
        "pages": page,
        "fetched": time.strftime("%Y-%m-%d %H:%M"),
    }
    if err is None:
        json.dump(rec, open(p, "w"))
    return rec, False


t0 = time.time()
n = 0
errs = collections.Counter()
tot = 0
items = sorted((str(v[1]), s) for s, v in codes.items() if v)
for i, (code, sym) in enumerate(items):
    for F, T in WINDOWS:
        rec, cached = window(code, F, T)
        if not cached:
            n += 1
            time.sleep(0.6)
        if rec.get("err"):
            errs[rec["err"]] += 1
        tot += len(rec.get("rows") or [])
    if (i + 1) % 10 == 0:
        print(
            "[%d/%d] %s %s rows-so-far=%d fetches=%d errs=%s (%.0fs)"
            % (i + 1, len(items), sym, code, tot, n, dict(errs), time.time() - t0)
        )
        sys.stdout.flush()
print("DONE symbols", len(items), "rows", tot, "fetches", n, "errs", dict(errs), "(%.0fs)" % (time.time() - t0))
