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
"""Harvest a backfill-workflow's agent results from its journal, RE-VERIFY each value against the
stored series (gap-real + magnitude + con==std consistency), then apply PASS cells fill-only to
docs/sf_fundamentals.json AND scripts/fundamentals.json. FLAG the rest for manual review.
Usage: python -X utf8 _wf_apply.py <run_journal_dir> [--apply]
Without --apply it's a DRY RUN (reports only). With --apply it writes both files.
"""
import json
import os
import re
import statistics
import sys

RUNDIR = sys.argv[1]
APPLY = "--apply" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(HERE, "fundamentals.json")

# 1) harvest all results from journal (robust to partial/killed runs)
res = []
jp = os.path.join(RUNDIR, "journal.jsonl")
for line in open(jp, encoding="utf-8"):
    try:
        j = json.loads(line)
    except:
        continue
    if j.get("type") == "result":
        r = j.get("result") or {}
        if isinstance(r, dict):
            for x in r.get("results", []) or []:
                res.append(x)
print("harvested results:", len(res))

data = json.load(open(DOCS))


def rec(s):
    return data.get(s, [])


def row(s, q):
    return next((x for x in rec(s) if x[0] == int(q)), None)


def ser(s, q, idx):
    r = row(s, q)
    return r[idx] if r and len(r) > idx else None


def neighbors(s, q, idx):
    vals = []
    for _dq in (-10000, 10000, -100, +100, -8700, +8700):  # ±yr same q, prior/next q-ish
        pass
    # collect same-basis values within ±5 quarters by index distance
    arr = sorted(rec(s), key=lambda x: x[0])
    qs = [x[0] for x in arr]
    i = qs.index(int(q)) if int(q) in qs else min(range(len(qs)), key=lambda k: abs(qs[k] - int(q))) if qs else None
    if i is None:
        return vals
    for k in range(max(0, i - 5), min(len(arr), i + 6)):
        v = arr[k][idx] if len(arr[k]) > idx else None
        if v is not None and arr[k][0] != int(q):
            vals.append(v)
    return vals


PASS = []
FLAG = []
for x in res:
    s = x.get("sym")
    q = int(x.get("qe"))
    basis = x.get("basis")
    v = x.get("value_cr")
    ann = x.get("announce_date")
    conf = x.get("confidence", "?")
    anchor = x.get("anchor") or ""
    idx = 3 if basis == "con" else 1
    didx = 4 if basis == "con" else 2
    r = row(s, q)
    reasons = []
    # gap-real (no overwrite)
    if r is not None and len(r) > idx and r[idx] is not None:
        FLAG.append((s, q, basis, v, conf, f"already filled={r[idx]}"))
        continue
    # con==std consistency: if con fill and std known, and anchor implies no-sub/con==std, value must ~= std
    if basis == "con":
        std = ser(s, q, 1)
        nosub = bool(re.search(r"no[- ]?sub|con==std|con=std|no subsidiary|identity|standalone", anchor, re.IGNORECASE))
        if std is not None and nosub and abs((v or 0) - std) > 0.05:
            reasons.append(f"nosub-claim but value {v:.2f} != std {std:.2f}")
        if std is not None and not nosub and abs((v or 0) - std) <= 0.01:
            pass  # con==std numerically; fine
    # magnitude sanity vs neighbors (same basis) -- SKIP for con==std identity copies
    # (a con value that exactly equals an already-stored, NSE-sourced std is validated by the std's
    #  own provenance; magnitude vs neighbors gives false positives across growth jumps/mergers).
    std_exact = basis == "con" and ser(s, q, 1) is not None and v is not None and abs(v - ser(s, q, 1)) <= 0.01
    nb = [] if std_exact else neighbors(s, q, idx)
    if not nb and basis == "con" and not std_exact:
        nb = neighbors(s, q, 1)  # fall back to std neighbors
    if nb:
        med = statistics.median(abs(n) for n in nb if n is not None) or 1
        av = abs(v) if v is not None else 0
        if med > 0 and (av > med * 9 or (av < med / 9 and av > 0.005)):
            reasons.append(f"magnitude {v:.2f} vs neighbor-median {med:.2f} (>9x)")
    # confidence
    if conf != "high":
        reasons.append(f"confidence={conf}")
    if reasons:
        FLAG.append((s, q, basis, v, conf, "; ".join(reasons)))
    else:
        PASS.append((s, q, basis, v, ann, anchor))

print("\nPASS:", len(PASS), "| FLAG:", len(FLAG))
from collections import Counter

print("PASS by sym:", dict(Counter(p[0] for p in PASS)))
if FLAG:
    print("\n--- FLAGGED (manual review) ---")
    for f in FLAG:
        print("  ", f[0], f[1], f[2], f"val={f[3]}", f"conf={f[4]}", "::", f[5])

if APPLY and PASS:
    for p in (DOCS, MIRROR):
        d = json.load(open(p))
        n = 0
        for s, q, basis, v, ann, anchor in PASS:
            idx = 3 if basis == "con" else 1
            didx = 4 if basis == "con" else 2
            rc = d.setdefault(s, [])
            r = next((x for x in rc if x[0] == int(q)), None)
            if r is None:
                r = [int(q), None, None, None, None]
                rc.append(r)
                rc.sort(key=lambda x: x[0])
            while len(r) < 5:
                r.append(None)
            if r[idx] is None:
                r[idx] = round(v, 2)
                if ann:
                    r[didx] = int(ann)
                elif r[didx] is None and basis == "con" and r[2] is not None:
                    r[didx] = r[2]  # copy std date for con=std
                n += 1
        json.dump(d, open(p, "w"), separators=(",", ":"))
        print("applied", n, "->", p)
    # save flagged for review
    json.dump(
        [{"sym": f[0], "qe": f[1], "basis": f[2], "value_cr": f[3], "confidence": f[4], "reason": f[5]} for f in FLAG],
        open(os.path.join(HERE, "_wf_flagged.json"), "w"),
        indent=0,
    )
elif not APPLY:
    print("\n(DRY RUN — re-run with --apply to write)")
