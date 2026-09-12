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
"""MEASURE the MC deep-feed reach for the by-product cells — CACHE ONLY, zero requests.

memory: feedback-measure-source-reach-first — reach is measured before a route is planned around.
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import agg_sources as AG  # noqa: E402

# NO_PERSIST — the cache-only stub below makes mc_id() fail for any symbol whose autosuggest body
# is not on disk, and mc_id PERSISTS its result. Without this an offline run writes `"SYM": null`
# into _agg_ids_mc.json, and a later ONLINE run then skips fetching it: absence manufactured from
# our own gap (memory: feedback-never-infer-absence-from-own-gaps).
# Redirect the write, do not neuter json.dump — `json.dump(obj, open(path,"w"))` truncates the file
# while evaluating its own arguments, so a no-op dump leaves an EMPTY id map behind (measured).
AG._MC_IDS = json.load(open(AG._MC_IDS_PATH, encoding="utf-8"))
AG._MC_IDS_PATH = os.path.join(HERE, "_vintage109_mc_ids_scratch.json")

CACHE_ONLY = True
_real_get = AG._get


def cached_only(host, url, pace, site, key, ttl=86400 * 3, headers=None, sess=None, tries=3):
    return AG._cached(site, key, 10**9)  # never expire, never fetch


def main():
    if CACHE_ONLY:
        AG._get = cached_only
    b = json.load(open(os.path.join(HERE, "_vintage109_byprod.json")))["cells"]
    cnt, per = Counter(), {}
    for _k, r in sorted(b.items()):
        sym, qe, basis = r["sym"], r["qe"], r["basis"]
        ck = (sym, basis)
        if ck not in per:
            try:
                per[ck] = AG.mc_quarters(sym, basis == "con")
            except Exception as e:
                per[ck] = ({}, f"err {e}")
        q, note = per[ck]
        row = q.get(qe)
        if not q:
            cnt["no cached MC table ({})".format(note.split(":")[0])] += 1
            r["mc"] = None
            r["mc_note"] = note
        elif row is None:
            cnt["cached table, quarter ABSENT"] += 1
            r["mc"] = None
            r["mc_note"] = note
        else:
            cnt["quarter PRESENT"] += 1
            r["mc"] = dict(row.items())
            r["mc_note"] = note
    print("MC cache-only reach over %d by-product cells:" % len(b))
    for kk, n in cnt.most_common():
        print("   %-42s %d" % (kk, n))
    got = [r for r in b.values() if r.get("mc")]
    print(
        "\nfields available on the %d reached cells: %s"
        % (len(got), Counter(f for r in got for f in r["mc"] if not f.endswith("_label")).most_common())
    )
    json.dump({"cells": b}, open(os.path.join(HERE, "_vintage109_byprod.json"), "w"), indent=1)
    print("merged MC readings into _vintage109_byprod.json")


if __name__ == "__main__":
    main()
