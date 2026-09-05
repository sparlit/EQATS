# -*- coding: utf-8 -*-
"""Point-in-time N500 membership from docs/stock_data.bin indicesHistory (120 snapshots,
2002-10-02->date after STEP M1+M2). Same interface used across the rev-mission worktree:
membership(yyyymmdd) -> set of rename-normed symbols.
"""
import os, json, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

rmap = json.load(open(os.path.join(HERE, "_rename_map.json"), encoding="utf8"))


def norm(s):
    s = str(s).strip().upper()
    seen = set()
    while s in rmap and s not in seen and rmap[s] != s:
        seen.add(s)
        s = rmap[s]
    return s


def _load():
    D = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "stock_data.bin"), "rb").read()))
    snaps = [(s["effectiveDate"].replace("-", ""), frozenset(norm(x) for x in s["symbols"] if not str(x).upper().startswith("DUMMY")))
             for s in D["indicesHistory"]["Nifty 500"]]
    snaps.sort()
    return snaps


_SNAPS = None


def membership(D):
    """Members as of yyyymmdd int: the nearest snapshot AT OR BEFORE the date."""
    global _SNAPS
    if _SNAPS is None:
        _SNAPS = _load()
    d = str(D)
    best = None
    for ed, syms in _SNAPS:
        if ed <= d:
            best = syms
        else:
            break
    return set(best) if best else set()
