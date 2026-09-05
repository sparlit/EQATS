# -*- coding: utf-8 -*-
"""ONE-TIME (re-runnable) backfill: parse the insurer XBRLs already in scripts/_xbrl_cache/
(INTEGRATED_FILING_LI_* life / INTEGRATED_FILING_GI_* general, ~2025+) with build_revop's
insurer-aware parser and upsert rev/op/pat cells into docs/sf_revop.json +
scripts/revop_fundamentals.json. Insurer rows previously existed as all-None (the old parser
had no IRDAI branch) — filled values OVERWRITE None, never a real number from a LATER filing
(files walked ascending by timestamp, latest wins, same as build_revop).

Run: python -X utf8 backfill_insurer_revop.py
"""
import os, json
from build_revop import parse_file, ts_key, CACHE, OUT, DOCS_OUT


def upsert(data, r):
    d = data.setdefault(r["sym"], {})
    row = d.get(str(r["qe"])) or [None, None, None, None, None, None, 0, None, None]
    if len(row) < 9:
        row += [None] * (9 - len(row))
    if r["fin"]:
        row[6] = 1
    def put(idx, val):
        if val is not None:
            row[idx] = round(val, 2)
    if r["std"]:
        put(0, r["std"]["rev"]); put(2, r["std"]["op"]); put(4, r["std"]["pat"])
    if r["con"]:
        put(1, r["con"]["rev"]); put(3, r["con"]["op"]); put(5, r["con"]["pat"])
    d[str(r["qe"])] = row


def main():
    files = sorted([f for f in os.listdir(CACHE) if "_LI_" in f or "_GI_" in f], key=ts_key)
    print("insurer cache files:", len(files))
    results = []
    for f in files:
        try:
            r = parse_file(os.path.join(CACHE, f), f)
        except Exception as e:
            print("  parse fail", f, e); continue
        if r:
            results.append(r)
    print("parsed:", len(results))
    for path in (DOCS_OUT, OUT):
        try:
            data = json.load(open(path))
        except Exception:
            print("skip (missing):", path); continue
        for r in results:
            upsert(data, r)
        json.dump(data, open(path, "w"), separators=(",", ":"))
        print("updated", path)
    # show what we now hold per insurer
    data = json.load(open(DOCS_OUT))
    for sym in sorted({r["sym"] for r in results}):
        qs = data.get(sym, {})
        have = [q for q, row in sorted(qs.items()) if row[0] is not None or row[1] is not None]
        print("%-12s rev/op quarters: %s" % (sym, have))


if __name__ == "__main__":
    main()
