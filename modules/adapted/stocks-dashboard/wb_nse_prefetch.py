# -*- coding: utf-8 -*-
"""Warm scripts/_wbnse_cache/ with a small worker pool, so wb_nse_results.py runs at cache speed.

Sequential fetching measured ~10.5s/page against web.archive.org (rate limiting, not latency), so
a 1,600-cell sweep is ~4.7 hours of wall clock. STEP W used a 4-worker prefetch pool against the
same host; this is that pattern, kept SEPARATE from the gate so the gate stays deterministic and
re-runnable offline.

⚠️ A failed fetch is recorded, never cached as empty: STEP W's own post-mortem is that reading a
cache miss during a wayback outage as "the data does not exist" produced 92 false refusals.

  python3 -X utf8 scripts/wb_nse_prefetch.py --cells <cells.json> --index <wb_index.json> [--workers 4]
"""
import argparse, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wb_nse_results as W                                          # noqa: E402

_lock = threading.Lock()
_done = {"n": 0, "ok": 0, "fail": 0}


def one(job):
    s, q, ts, u = job
    t = W.fetch(ts, u, tries=2)
    with _lock:
        _done["n"] += 1
        _done["ok" if t else "fail"] += 1
        if _done["n"] % 100 == 0:
            print("  [%d] ok=%d fail=%d" % (_done["n"], _done["ok"], _done["fail"]))
            sys.stdout.flush()
    return t is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    idx = json.load(open(a.index))
    jobs = []
    for s, q in json.load(open(a.cells)):
        k = "%s|%d" % (s, int(q))
        if k in idx:
            jobs.append((s, int(q), idx[k][0], idx[k][1]))
    print("prefetching %d pages with %d workers" % (len(jobs), a.workers))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, jobs))
    print("DONE ok=%d fail=%d in %.0fs (%.1fs/page effective)"
          % (_done["ok"], _done["fail"], time.time() - t0, (time.time() - t0) / max(1, len(jobs))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
