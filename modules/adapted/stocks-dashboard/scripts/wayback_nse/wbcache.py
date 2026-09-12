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
"""Disk-cached fetcher for archived NSE results.jsp pages, over a KEEP-ALIVE session.

⚠️ MEASURED 2026-08-26: a new TCP connection per request gets "Connection refused" from
web.archive.org roughly 90% of the time under any sustained load, and a 4-worker pool made it
worse, not better -- 2 ok / 23 fail. The same pages over ONE persistent requests.Session at a
0.4s pace: 13 ok / 1 fail, 1.0s per page. So the bottleneck was connection churn, not a rate
limit on bytes, and the fix is keep-alive + serial, not more workers.

⚠️ A transport failure is NEVER cached and NEVER evidence about the data (STEP W's audit #1 read
"absent from cache" during a wayback outage as "not fetchable" -- that measures the outage).
"""
import gzip
import hashlib
import os
import time

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "wayback_nse")
os.makedirs(CACHE, exist_ok=True)
_SESS = None


def _session():
    global _SESS
    if _SESS is None:
        import requests

        s = requests.Session()
        s.headers.update(
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept-Encoding": "gzip, deflate"}
        )
        _SESS = s
    return _SESS


def _path(ts, url):
    return os.path.join(CACHE, hashlib.sha1((ts + "|" + url).encode()).hexdigest() + ".gz")


def cached(ts, url):
    p = _path(ts, url)
    if not os.path.exists(p):
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return f.read() or ""
    except Exception:
        return None


def fetch_cached(ts, url, tries=5, pace=0.4):
    c = cached(ts, url)
    if c is not None:
        return c or None
    full = f"https://web.archive.org/web/{ts}id_/{url}"
    for a in range(tries):
        try:
            r = _session().get(full, timeout=75)
            if r.status_code == 200:
                t = r.text
                with gzip.open(_path(ts, url), "wt", encoding="utf-8") as f:
                    f.write(t)
                time.sleep(pace)
                return t
            if r.status_code in (404, 403):
                return None  # a real answer from the archive, still not cached
        except Exception:
            pass
        time.sleep(min(0.8 + 0.8 * a, 5.0))
    return None


def prefetch(items, log_every=25):
    todo = [(t, u) for t, u in items if cached(t, u) is None]
    hit = len(items) - len(todo)
    got = fail = 0
    for i, (t, u) in enumerate(todo):
        if fetch_cached(t, u):
            got += 1
        else:
            fail += 1
        if (i + 1) % log_every == 0:
            print(f"    prefetch {i + 1}/{len(todo)}  ok={got} fail={fail}", flush=True)
    return hit, got, fail
