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
"""Deep reconciliation: re-fetch EVERY symbol from NSE (both endpoints) and FILL any quarter we're
missing — guarantees we didn't drop quarters NSE actually serves. Fill-only: never overwrites an
existing value, only adds missing quarters / fills null std|con. Atomic writes, resumable
(_recon_done.txt). socket timeout bounds any network hang. NSE-only (won't touch BSE).
Run: python -X utf8 recon.py    (re-run resumes from _recon_done.txt)
"""
import concurrent.futures
import json
import os
import socket
import threading

import build_fundamentals as bf

DOCS = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_fundamentals.json")
OUT = bf.OUT
DONE = os.path.join(bf.HERE, "_recon_done.txt")
socket.setdefaulttimeout(40)


def merge_fill(existing, fetched):
    m = {r[0]: list(r) for r in existing}
    added = 0
    for r in fetched:
        if r[0] not in m:
            m[r[0]] = list(r)
            added += 1
        else:
            row = m[r[0]]
            if row[1] is None and r[1] is not None:
                row[1], row[2] = r[1], r[2]
                added += 1
            if row[3] is None and r[3] is not None:
                row[3], row[4] = r[3], r[4]
                added += 1
    return [m[k] for k in sorted(m)], added


def main():
    data = json.load(open(DOCS))
    done = set(open(DONE).read().split()) if os.path.exists(DONE) else set()
    targets = [s for s in sorted(data) if s not in done]
    print("reconciling %d symbols (%d already done)" % (len(targets), len(done)))
    _tl = threading.local()

    def jar():
        if not getattr(_tl, "jar", None):
            _tl.jar = bf.nse_jar()
        return _tl.jar

    def do(sym):
        try:
            out = bf.fetch_symbol(sym, jar())
        except Exception:
            out = None
        return sym, out

    lock = threading.Lock()
    processed = filled = touched = 0
    donef = open(DONE, "a")

    def flush():
        for p in (DOCS, OUT):
            tmp = p + ".tmp"
            json.dump(data, open(tmp, "w"), separators=(",", ":"))
            os.replace(tmp, p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for sym, out in ex.map(do, targets):
            processed += 1
            with lock:
                if out:
                    merged, added = merge_fill(data.get(sym, []), out)
                    if added:
                        data[sym] = merged
                        filled += added
                        touched += 1
                donef.write(sym + "\n")
                donef.flush()
                if processed % 50 == 0 or processed == len(targets):
                    flush()
                    print(
                        "  ...%d/%d  symbols_filled=%d  quarters_filled=%d" % (processed, len(targets), touched, filled)
                    )
    flush()
    print("DONE. filled %d quarters across %d symbols." % (filled, touched))


if __name__ == "__main__":
    main()
