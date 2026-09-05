# -*- coding: utf-8 -*-
"""
Heal meta.alive / meta.ind / meta.name on an already-built sf_stock_data.bin, without redoing
the multi-hour bhavcopy rebuild.

Root cause (found 2026-08-02): build_sf_data.py's "currently listed" lookup used to scrape a
<script id="compressedData"> blob out of docs/nse-bse-dashboard.html. That page was refactored
to load its data from dash_slim.bin instead, so the blob has not existed for a while — the
scrape's bare `except` silently left the lookup EMPTY, and every full rebuild since then wrote
alive=False + industry="Unknown" for EVERY symbol (verified live: RELIANCE/TCS/INFY included).
build_sf_data.py now reads dash_slim.bin directly (see the commit that added this script); this
script re-derives the same fields for a bin that was already built with the broken lookup,
so the fix doesn't require re-fetching 30 years of bhavcopies.

Second root cause (found 2026-08-12, DATA_RUNBOOK §94): dash_slim membership ALONE is the wrong
oracle — it is an NSE **+ BSE** universe keyed `SYM.NS`/`SYM.BO` and the lookup strips the suffix,
so a company that left the NSE cash segment but still trades on BSE marked its dead NSE tape alive
(87 symbols on the live bin, PUNJCOMMU's stopped 2003-03-31). `alive` now also requires the series'
LAST BAR to be within build_sf_data.ALIVE_RECENCY_DAYS of the bin's own `end`.

Run: python3 -X utf8 scripts/patch_sf_alive.py [bin_path] [dash_slim_path]
Defaults: docs/sf_stock_data.bin, docs/dash_slim.bin
"""
import os, sys, json, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")

sys.path.insert(0, HERE)
# build_sf_data parses sys.argv[1:] as its own START/DAILY_FROM dates at import time — hide our
# args (bin_path / slim_path) from it or it crashes trying to read a path as a date.
_argv = sys.argv; sys.argv = _argv[:1]
import build_sf_data as B   # alive_cutoff / ALIVE_RECENCY_DAYS — one definition of "alive"
sys.argv = _argv


def main():
    bin_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DOCS, "sf_stock_data.bin")
    slim_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(DOCS, "dash_slim.bin")

    slim = json.loads(gzip.decompress(open(slim_path, "rb").read()))
    cur = {}
    for k, m in (slim.get("meta") or {}).items():
        sym = m.get("symbol") or k.split(".")[0]
        cur[sym] = {"name": m.get("name"), "industry": m.get("industry") or m.get("sector")}
    if not cur:
        sys.exit("ABORT: currently-listed universe (%s meta) came out EMPTY — refusing to mark "
                  "every symbol dead." % slim_path)
    print("currently-listed universe: %d symbols (from %s)" % (len(cur), slim_path))

    big = json.loads(gzip.decompress(open(bin_path, "rb").read()))
    meta, data = big["meta"], big.get("data") or {}
    before_alive = sum(1 for m in meta.values() if m.get("alive"))
    # freshness half of the rule — judged against the BIN's own `end`, never today's date, so a
    # deliberately frozen snapshot isn't declared dead wholesale (§11 / §94).
    cut = B.alive_cutoff(big.get("end"))
    if cut is None:
        sys.exit("ABORT: bin has no usable `end` (%r) — cannot judge series freshness." % big.get("end"))
    print("alive also requires a bar on/after %d (%dd before the bin's end %s)"
          % (cut, B.ALIVE_RECENCY_DAYS, big.get("end")))

    changed = n_stale = 0
    for sym, m in meta.items():
        c = cur.get(sym)
        d = (data.get(sym) or {}).get("d")
        fresh = bool(d) and d[-1] >= cut
        new_alive = (sym in cur) and fresh
        if sym in cur and not fresh:
            n_stale += 1
        new_ind = (c or {}).get("industry") or "Unknown"
        new_name = (c or {}).get("name") or sym
        if m.get("alive") != new_alive or m.get("ind") != new_ind or m.get("name") != new_name:
            changed += 1
        m["alive"] = new_alive
        m["ind"] = new_ind
        m["name"] = new_name

    after_alive = sum(1 for m in meta.values() if m.get("alive"))
    print("meta entries: %d   changed: %d   alive before: %d   alive after: %d   "
          "(in dash_slim but series stale -> dead: %d)"
          % (len(meta), changed, before_alive, after_alive, n_stale))
    # Sanity circuit-breaker. It guards ONE failure mode — the empty/degenerate `cur` this script
    # exists to undo — so it must measure the MEMBERSHIP half, not the final alive count. Those are
    # no longer the same number: `alive` now also requires a fresh series, and the share of the
    # 30-year universe still trading falls a little every year purely because dead symbols
    # accumulate (2026-08-12: matched 2,461, alive 2,373 of 4,445). Gating on `after_alive` would
    # therefore have become a false tripwire on a healthy file.
    matched = sum(1 for sym in meta if sym in cur)
    if matched < len(meta) * 0.5:
        sys.exit("ABORT: only %d/%d bin symbols matched the currently-listed universe (<50%%) — "
                  "suspiciously low, refusing to write. Investigate before re-running."
                  % (matched, len(meta)))

    blob = gzip.compress(json.dumps(big, separators=(",", ":")).encode(), 6)
    open(bin_path, "wb").write(blob)
    print("Wrote %s (%.2f MB)" % (bin_path, len(blob) / 1048576))


if __name__ == "__main__":
    main()
