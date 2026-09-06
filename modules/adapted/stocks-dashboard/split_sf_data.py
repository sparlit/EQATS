# -*- coding: utf-8 -*-
"""Split docs/sf_stock_data.bin (the full survivorship-free price file, ~190MB gz since the
2026-08-02 true-daily-bars rebuild) into a BY-DATE layout for the sf-data Pages repo:

  sf_recent_*.bin   bars from DEEP_FROM (2019-01-01) onward — all a quick run needs: the default
                    backtest window (2020-03-31) and every wave preset (Mar'20+) keep a full 365d
                    lookback inside it, at ~1/3 the bytes of the whole payload.
  sf_deep_*.bin     bars BEFORE DEEP_FROM (by-symbol chunks). The browser fetches these lazily,
                    only when a run's window actually starts before ~2020 (ensureDeepHistory()).
  sf_meta.json      {end, rev, deepFrom, fullStart, recent, deep, nTot, nDead} — loaders detect
                    the layout by `deepFrom` (absent = legacy by-symbol sf_stock_data_*.bin) and
                    show full universe stats/date ranges without loading the deep parts.

Pre-DEEP_FROM bars never change day-to-day (appends touch the tail only), so a client mixing a
cached recent part with a next-day deep part is harmless.

Each section auto-sizes its part count (ceil(section_gz/95MB)) — grows as the dataset grows.

Run: python split_sf_data.py [src.bin] [out_dir]
"""
import json, gzip, os, sys, hashlib
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "sf_stock_data.bin")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "_sfsplit")
os.makedirs(OUT, exist_ok=True)

DEEP_FROM = "2019-01-01"          # recent floor: earliest wave preset (2020-03-31) minus 365d lookback, with margin
DEEP_CUT = 20190101               # same, as the bin's YYYYMMDD ints
CAP = 95 * 1024 * 1024            # sf-data force-pushes each part as a single git blob; GitHub hard-caps at 100MB

def slice_sym(o, lo, hi):
    """Slice every per-bar array of a symbol's record to [lo:hi] (keys of len == len(d))."""
    n = len(o["d"])
    return {k: (v[lo:hi] if isinstance(v, list) and len(v) == n else v) for k, v in o.items()}

def write_section(name, section, other, meta, fp):
    """Write one section (recent/deep) as N alphabetical by-symbol chunks, each <CAP compressed.
    Feeds every part's payload into `fp` (the content fingerprint). Returns part count."""
    syms = sorted(section.keys())
    sec_gz = gzip.compress(json.dumps({"data": section, "meta": {s: meta[s] for s in syms if s in meta}},
                                      separators=(",", ":")).encode(), 6)
    n_parts = max(1, -(-len(sec_gz) // CAP))
    chunk = -(-len(syms) // n_parts)
    groups = [syms[i:i + chunk] for i in range(0, len(syms), chunk)]
    print("%s section %.1f MB compressed -> %d part(s)" % (name, len(sec_gz) / 1048576, len(groups)), flush=True)
    for part, grp in enumerate(groups, 1):
        obj = dict(other)
        obj["data"] = {s: section[s] for s in grp}
        obj["meta"] = {s: meta[s] for s in grp if s in meta}
        payload = json.dumps(obj, separators=(",", ":")).encode()
        fp.update(payload)          # fingerprint the DATA, before compression (see the rev note below)
        # mtime=0: gzip stamps the CURRENT TIME into its header by default, so byte-identical data
        # compressed twice produced different files. Pinning it keeps the published file byte-stable,
        # which also lets HTTP ETags/CDNs treat an unchanged rebuild as genuinely unchanged.
        raw = gzip.compress(payload, 9, mtime=0)
        if len(raw) > CAP:
            raise SystemExit("ABORT: sf_%s_%d.bin is %.1f MB (>95MB cap) — part sizing is broken"
                             % (name, part, len(raw) / 1048576))
        open(os.path.join(OUT, "sf_%s_%d.bin" % (name, part)), "wb").write(raw)
        print("%s %d: %d symbols, %.1f MB" % (name, part, len(grp), len(raw) / 1048576), flush=True)
    return len(groups)

def main():
    D = json.loads(gzip.decompress(open(SRC, "rb").read()))
    data = D["data"]; meta = D.get("meta", {})
    # GUARD: never publish an UN-merged build (renamed tickers split into stub series). If the
    # rename merge didn't run, ETERNAL (ex-ZOMATO) has only ~post-rename days and ZOMATO still
    # exists as its own series. Fail loud so the workflow stops instead of pushing bad data to sf-data.
    et = data.get("ETERNAL")
    if "ZOMATO" in data or not et or len(et.get("d", [])) < 1000:
        raise SystemExit("ABORT: bin looks UN-merged (ZOMATO present or ETERNAL history short) — refusing to publish")

    other = {k: v for k, v in D.items() if k not in ("data", "meta")}
    recent, deep = {}, {}
    for sym, o in data.items():
        k = bisect_left(o["d"], DEEP_CUT)
        if k < len(o["d"]):
            recent[sym] = slice_sym(o, k, len(o["d"]))
        if k > 0:
            deep[sym] = slice_sym(o, 0, k)

    fp = hashlib.sha1()
    rec_other = dict(other); rec_other["start"] = DEEP_FROM
    n_recent = write_section("recent", recent, rec_other, meta, fp)
    n_deep = write_section("deep", deep, other, meta, fp)

    # CONTENT fingerprint, not just `end`: a heal/backfill run (e.g. the delivery-% ledgers) rewrites
    # history WITHOUT advancing `end`, and the browser keys its IndexedDB copy of these 100+ MB parts
    # on this file. Keyed on `end` alone, every client that had already cached the day kept serving
    # the PRE-heal bytes forever. `rev` hashes the PAYLOAD, not the gzip container, so it changes
    # exactly when the data does.
    rev = fp.hexdigest()[:10]
    # `dailyFrom` (2002-01-02) is where TRUE daily bars begin — everything before it is weekly, where
    # the oscillator family (RSI/MACD/stoch/volatility) can't be computed meaningfully. The site's
    # full-history window starts there rather than at `fullStart` (1996) for exactly that reason.
    json.dump({"end": D["end"], "rev": rev, "deepFrom": DEEP_FROM, "fullStart": D.get("start", ""),
               "dailyFrom": D.get("dailyFrom", ""),
               "recent": n_recent, "deep": n_deep, "nTot": len(data),
               "nDead": sum(1 for s in data if not (meta.get(s) or {}).get("alive"))},
              open(os.path.join(OUT, "sf_meta.json"), "w"))
    print("split done; end=%s rev=%s deepFrom=%s recent=%d deep=%d"
          % (D["end"], rev, DEEP_FROM, n_recent, n_deep), flush=True)

if __name__ == "__main__":
    main()
