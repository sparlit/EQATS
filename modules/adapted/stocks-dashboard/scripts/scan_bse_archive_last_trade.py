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
"""DATA_RUNBOOK §145 — one-off tool behind scripts/bse_last_trade_archive.json.
Usage: python3 scripts/scan_bse_archive_last_trade.py CODES.json   (a JSON list of BSE scrip codes)
Scan BSE's daily equity archive backwards (2023-12-03 -> 2007-01-01) for the LAST trade of a set of
scrip codes. Most-recent-first; a code is done at its first hit. Per-day results cached in CACHE so a
rerun resumes. Files: EQ_ISINCODE_DDMMYY.zip (has TRADING_DATE inside) else EQDDMMYY_CSV.ZIP."""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import contextlib
import csv
import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import bse_headers as BH  # §181 BSE headers

SC = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(SC, "_bse_arch")  # gitignored (scripts/_*); os.makedirs(CACHE, exist_ok=True)
CODES = set(json.load(open(sys.argv[1])))
START, END = datetime.date(2023, 12, 3), datetime.date(2007, 1, 1)


def get(url):
    r = subprocess.run(
        ["curl", "-s", "--max-time", "60", "-A", BH.UA, *BH.CURL_ARGS, url], capture_output=True, timeout=75
    )
    return r.stdout


def day(d):
    """-> {"sig": str, "date_inside": iso|None, "hits": {code: [close, trades, shares]}} or None (no file)."""
    p = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    ddmmyy = d.strftime("%d%m%y")
    for url in (
        f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{ddmmyy}.zip",
        f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{ddmmyy}_CSV.ZIP",
    ):
        for attempt in range(3):
            try:
                blob = get(url)
                break
            except Exception:
                blob = b""
                time.sleep(2 + attempt)
        if not blob.startswith(b"PK"):
            continue
        try:
            z = zipfile.ZipFile(io.BytesIO(blob))
            t = z.read(z.namelist()[0]).decode("utf-8", "replace")
        except Exception:
            continue
        rows = list(csv.DictReader(io.StringIO(t)))
        if len(rows) < 500:
            continue
        sig = hashlib.sha1(
            "|".join(
                "{}:{}".format(r.get("SC_CODE", "").strip(), r.get("CLOSE", "").strip()) for r in rows[:400]
            ).encode()
        ).hexdigest()
        di = None
        td = (rows[0].get("TRADING_DATE") or "").strip()
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                di = datetime.datetime.strptime(td, fmt).date().isoformat()
                break
            except ValueError:
                pass
        hits = {}
        for r in rows:
            c = (r.get("SC_CODE") or "").strip()
            if c in CODES:
                with contextlib.suppress(ValueError):
                    hits[c] = [
                        float(r.get("CLOSE") or 0),
                        int(float(r.get("NO_TRADES") or 0)),
                        int(float(r.get("NO_OF_SHRS") or 0)),
                    ]
        out = {"sig": sig, "date_inside": di, "hits": hits, "url": url.rsplit("/", 1)[-1]}
        json.dump(out, open(p, "w"))
        return out
    json.dump(None, open(p, "w"))  # confirmed: neither format has a file for this date
    return None


days = []
d = START
while d >= END:
    if d.weekday() < 5:
        days.append(d)
    d -= datetime.timedelta(days=1)
print("scanning %d weekdays %s -> %s for %d codes" % (len(days), START, END, len(CODES)), flush=True)
done = 0
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    for _ in ex.map(day, days):
        done += 1
        if done % 250 == 0:
            print("  %d/%d (%.0fs)" % (done, len(days), time.time() - t0), flush=True)
# most recent hit per code, with the re-serve guard: if the hit day's file is byte-identical (signature)
# to an OLDER day's file, the hit date is a holiday re-serve and the real session is the oldest twin
res = {}
cache = {d: day(d) for d in days}
for c in sorted(CODES):
    for i, d in enumerate(days):
        x = cache[d]
        if x and c in x["hits"]:
            real = d
            for d2 in days[i + 1 : i + 6]:
                y = cache.get(d2)
                if y and y["sig"] == x["sig"]:
                    real = d2
                elif y:
                    break
            res[c] = {
                "d": (x.get("date_inside") or real.isoformat()),
                "url_date": d.isoformat(),
                "close": x["hits"][c][0],
                "trades": x["hits"][c][1],
                "shares": x["hits"][c][2],
                "file": x["url"],
            }
            break
json.dump(res, open(os.path.join(SC, "_bse_archive_hits.json"), "w"), indent=1)
nofile = sum(1 for d in days if cache[d] is None)
print(
    "done in %.0fs: %d/%d codes found; %d weekdays had no file" % (time.time() - t0, len(res), len(CODES), nofile),
    flush=True,
)
for c, v in sorted(res.items(), key=lambda kv: kv[1]["d"], reverse=True):
    print("  ", c, v)
