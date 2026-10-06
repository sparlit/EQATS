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


#!/usr/bin/env python3
"""§164 ledger writer (Quantmac reply #2 round, user 2026-09-25 "adopt all three recommendations, do it").
Merges proposal files {"SYM|QE": {"was": cell, "cell": cell, "why": str, "src": str, ...}} into scripts/shp_cell_fix.json:
an entry is written only while the store still equals `was`; an existing entry for the cell is kept under `superseded`.
Evidence goes to scripts/_shp_164_audit.json, MERGED into what is there (never replaced — the 9609c489a lesson).
Usage: _shp_164_write.py <label> <proposals.json> [more.json ...]"""
import json
import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import fetch_shareholding as F

AUDIT = os.path.join(SCRIPTS, "_shp_164_audit.json")


def main(label, paths):
    P = {}
    for p in paths:
        P.update(json.load(open(p)))
    path = os.path.join(SCRIPTS, "shp_cell_fix.json")
    raw = open(path, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led.setdefault("fix", {})
    ascii_only = "\\u00" in raw
    hist = json.load(open(os.path.join(SCRIPTS, "shp_history.json")))
    audit = (
        json.load(open(AUDIT, encoding="utf-8"))
        if os.path.exists(AUDIT)
        else {"_doc": [], "cells": {}}
    )
    audit.setdefault("cells", {})
    audit.setdefault("_doc", [])
    n_new = n_sup = n_skip = 0
    for k, v in sorted(P.items()):
        s, q = k.split("|")
        cur = (hist.get(s) or {}).get(q)
        if cur is None or not F._cell_eq(cur, v["was"]):
            n_skip += 1
            continue
        ent = {"cell": list(v["cell"]), "was": list(cur), "src": v["src"], "why": v["why"]}
        prior = (fix.get(s) or {}).get(q)
        if prior:
            if not F._cell_eq(cur, prior.get("cell")):
                n_skip += 1
                continue
            ent["superseded"] = prior
            n_sup += 1
        else:
            n_new += 1
        fix.setdefault(s, {})[q] = ent
        audit["cells"][k] = {x: v[x] for x in v if x not in ("was", "cell", "why")}
        audit["cells"][k]["label"] = label
    json.dump(led, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=ascii_only)
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("%s: %d new, %d superseding, %d skipped (store moved)" % (label, n_new, n_sup, n_skip))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
