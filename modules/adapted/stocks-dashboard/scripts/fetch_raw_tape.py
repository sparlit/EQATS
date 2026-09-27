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
"""Cache NSE's RAW closes for every session the price bin holds — the exact witness for
audit_applied_factors.py --tape (DATA_RUNBOOK §161j).

Why: the bin stores  stored(t) = raw(t) x PROD{factors applied after t}, so stored/raw per bar is the
applied-factor product EXACTLY (to 2-decimal rounding). The audit's older witness, vw / (t*1e5/v), is
noisy wherever turnover is thin (t is kept to 0.1 lakh: +-30% at t=0.3) and its +-4-bar median merged
factors that sit one bar apart — NATNLSTEEL 2020 (§165f) was invisible to §161f for both reasons.

Cache: scripts/_raw_tape/<ymd>.json.gz = {"date": ymd, "rows": {SYM: [[series, close, prev_close, open], ...]}}
       (gitignored). Only a confirmed 404 from BOTH urls is cached as <ymd>.miss; anything else stays
       uncached so a re-run retries (§80f trap 1). A file whose own date column disagrees with the URL's
       date (NSE misdirect) is NOT cached and is listed as such.
Run:   python3 scripts/fetch_raw_tape.py <dir with sf_deep_*/sf_recent_* bins> [--from 20020101] [--to 20991231] [--workers 3]
"""
import csv
import datetime
import glob
import gzip
import io
import json
import os
import sys
import threading
import time
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_bz_backfill as B  # _urls / _get / jar — the same NSE fetch path the BZ tooling uses

TAPE = os.path.join(HERE, "_raw_tape")
SESSION_FLOOR = 100  # a date with >= this many symbol-bars is a session in the bin
local = threading.local()
FAILED, MISDIRECT = [], []


def sessions(bindir, lo, hi):
    cnt = {}
    for f in sorted(glob.glob(os.path.join(bindir, "sf_deep_*.bin"))) + sorted(
        glob.glob(os.path.join(bindir, "sf_recent_*.bin"))
    ):
        D = json.loads(gzip.open(f).read())
        for o in D["data"].values():
            for y in o["d"]:
                if lo <= y <= hi:
                    cnt[y] = cnt.get(y, 0) + 1
    return sorted(y for y, n in cnt.items() if n >= SESSION_FLOOR)


def _parse(text, ymd):
    """-> (rows, file_date_or_None) or (None, None) when the body is not a bhavcopy."""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 300:
        return None, None
    hdr = [h.strip().upper() for h in rows[0]]

    def ix(*ns):
        return next((hdr.index(n) for n in ns if n in hdr), -1)

    iS, iSer, iC, iP, iO = (
        ix("SYMBOL"),
        ix("SERIES"),
        ix("CLOSE_PRICE", "CLOSE"),
        ix("PREV_CLOSE", "PREVCLOSE"),
        ix("OPEN_PRICE", "OPEN"),
    )
    iD = ix("DATE1", "TIMESTAMP")
    if min(iS, iSer, iC) < 0:
        return None, None

    def num(r, i):
        try:
            return float(r[i].strip()) if 0 <= i < len(r) and r[i].strip() not in ("", "-") else 0.0
        except ValueError:
            return 0.0

    out, fdate = {}, None
    for r in rows[1:]:
        if len(r) <= max(iS, iSer, iC):
            continue
        if fdate is None and iD >= 0 and iD < len(r) and r[iD].strip():
            for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
                try:
                    fdate = int(datetime.datetime.strptime(r[iD].strip(), fmt).strftime("%Y%m%d"))
                    break
                except ValueError:
                    pass
        c = num(r, iC)
        if c <= 0:
            continue
        out.setdefault(r[iS].strip(), []).append([r[iSer].strip(), c, num(r, iP), num(r, iO)])
    return out, fdate


def fetch(ymd):
    path = os.path.join(TAPE, "%d.json.gz" % ymd)
    miss = os.path.join(TAPE, "%d.miss" % ymd)
    if os.path.exists(path) or os.path.exists(miss):
        return
    d = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    urls = B._urls(d)
    saw404 = set()
    for attempt in range(3):
        if not hasattr(local, "jar") or attempt:
            local.jar = B.jar()
        for url in urls:
            try:
                blob = B._get(url, local.jar)
                if url.endswith(".zip"):
                    z = zipfile.ZipFile(io.BytesIO(blob))
                    text = z.read(z.namelist()[0]).decode("utf-8", "replace")
                else:
                    text = blob.decode("utf-8", "replace")
                rows, fdate = _parse(text, ymd)
                if rows is None:
                    continue
                if fdate is not None and fdate != ymd:
                    MISDIRECT.append((ymd, fdate, url))
                    continue  # NSE served another day's file
                with gzip.open(path + ".tmp", "wt") as fh:
                    json.dump({"date": ymd, "rows": rows}, fh, separators=(",", ":"))
                os.replace(path + ".tmp", path)
                return
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    saw404.add(url)
            except Exception:
                pass
        time.sleep(1.5 * (attempt + 1))
    if len(saw404) == len(urls):
        open(miss, "w").write("404")
    else:
        FAILED.append(ymd)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)

    def opt(k, dflt):
        return int(a[a.index(k) + 1]) if k in a else dflt

    lo, hi, workers = opt("--from", 20020101), opt("--to", 20991231), opt("--workers", 3)
    os.makedirs(TAPE, exist_ok=True)
    ss = sessions(a[0], lo, hi)
    todo = [
        y
        for y in ss
        if not os.path.exists(os.path.join(TAPE, "%d.json.gz" % y))
        and not os.path.exists(os.path.join(TAPE, "%d.miss" % y))
    ]
    print("sessions in bin %d..%d: %d; to fetch: %d" % (lo, hi, len(ss), len(todo)), flush=True)
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for _ in ex.map(fetch, todo):
            done += 1
            if done % 200 == 0:
                print(
                    "  %d/%d  transient %d  misdirect %d" % (done, len(todo), len(FAILED), len(MISDIRECT)), flush=True
                )
    have = sum(os.path.exists(os.path.join(TAPE, "%d.json.gz" % y)) for y in ss)
    miss = sum(os.path.exists(os.path.join(TAPE, "%d.miss" % y)) for y in ss)
    print(
        "tape: %d of %d sessions cached, %d confirmed 404, %d transient (re-run), %d misdirected: %s"
        % (have, len(ss), miss, len(FAILED), len(MISDIRECT), MISDIRECT[:10]),
        flush=True,
    )


if __name__ == "__main__":
    main()
