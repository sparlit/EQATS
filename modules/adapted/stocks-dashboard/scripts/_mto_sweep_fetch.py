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
"""§88b MTO sweep — FETCH stage. Downloads NSE security-wise-delivery MTO_DDMMYYYY.DAT
for every bin trading date that still has >=1 dv==0 bar (gap_dates.json from the baseline
measure). Validates CONTENT (10,MTO record), never size/exit-code (feedback-nse-dated-url-traps:
HTML error pages pass size checks). HTTP/1.1 + browser UA. Cache-dir resume: a file already
validated is never refetched, so the sweep is restartable."""
import json
import os
import queue
import random
import sys
import threading
import time
import urllib.error
import urllib.request

SP = os.environ.get("MTO_SP", os.path.expanduser("~/.cache/mto_sweep"))
CACHE = os.path.join(SP, "mto")
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
URL = "https://nsearchives.nseindia.com/archives/equities/mto/MTO_%s.DAT"


def valid_mto(body):
    head = body[:2000]
    return (b"10,MTO," in head) and (b"20," in body) and (b"<!DOCTYPE" not in head) and (b"<html" not in head)


def fetch_one(ymd):
    ddmmyyyy = f"{ymd[6:8]}{ymd[4:6]}{ymd[0:4]}"
    ok = os.path.join(CACHE, ymd + ".DAT")
    miss = os.path.join(CACHE, ymd + ".404")
    if os.path.exists(ok) or os.path.exists(miss):
        return "cached"
    req = urllib.request.Request(URL % ddmmyyyy, headers={"User-Agent": UA, "Accept": "*/*"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            if valid_mto(body):
                tmp = ok + ".tmp"
                open(tmp, "wb").write(body)
                os.rename(tmp, ok)
                return "ok"
            last = "invalid-content(%dB)" % len(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(miss, "w").write("404")
                return "404"
            last = "http%d" % e.code
        except Exception as e:
            last = type(e).__name__
        time.sleep(1.5 * (attempt + 1) + random.random())
    return "FAIL:" + last


def main():
    dates = [str(x) for x in json.load(open(os.path.join(SP, "gap_dates.json"))) if x >= 20020101]
    print("dates to sweep:", len(dates), flush=True)
    q = queue.Queue()
    for d in dates:
        q.put(d)
    stats = {}
    lock = threading.Lock()
    fails = []

    def worker():
        while True:
            try:
                d = q.get_nowait()
            except queue.Empty:
                return
            r = fetch_one(d)
            with lock:
                stats[r.split(":")[0]] = stats.get(r.split(":")[0], 0) + 1
                if r.startswith("FAIL"):
                    fails.append((d, r))
                n = sum(stats.values())
                if n % 250 == 0:
                    print(n, stats, flush=True)
            time.sleep(0.05 + random.random() * 0.1)

    ths = [threading.Thread(target=worker) for _ in range(6)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    print("DONE", stats, flush=True)
    if fails:
        json.dump(fails, open(os.path.join(SP, "mto_fetch_fails.json"), "w"), indent=0)
        print("failures written: %d -> mto_fetch_fails.json" % len(fails), flush=True)


if __name__ == "__main__":
    main()
