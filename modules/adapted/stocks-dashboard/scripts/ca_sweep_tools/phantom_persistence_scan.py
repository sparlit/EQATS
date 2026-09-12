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
"""UNIVERSE-WIDE phantom detector (runbook §126) — the persistence test on EVERY adjustment the bake applied,
both directions. A legitimate split/bonus/consolidation/crash re-bases the RAW price and it HOLDS. A phantom
(a muhurat/data glitch, a mis-chained gap) moves only the ADJUSTED series while the raw tape sits flat.

Input: the sweep's steps file (each {sym, ymd, applied, quant, ...}) + the bin + the raw bhav cache.
For every applied step with |applied-1| > 0.03 and not quantised, from the RAW tape (calendar-adjacent,
last actual trade up to 90d back; median of the next 2..8 trades forward):
    raw_step = rawclose(ex) / rawclose(prev actual trade)
    persist  = median(next trades) / rawclose(ex)
Flag PHANTOM when the raw price did NOT re-base to match the applied factor:
    raw_step in [0.80, 1.25]  (raw essentially flat)  AND  |applied-1| > 0.05
i.e. the bake applied a factor the tape never carried -> the pre-event history is mis-scaled by ~applied.
REAL when raw_step is within 12% of applied and persist in [0.8,1.25] (raw genuinely and durably re-based —
whether a real corporate action or a crash; crash-vs-action is §124's separate job, not this one).
Everything else -> REVIEW (partial re-base, snap-back, or no adjacent trade even at 90d).

Down-moves (applied<1) flagged PHANTOM are equally real bugs: a factor divided out of a flat tape.
Usage: phantom_persistence_scan.py <steps.json | sweep_out.json> <bin> <cache> <out.json>
Writes nothing to any ledger.
"""
import datetime
import gzip
import json
import os
import sys
from collections import Counter
from statistics import median

SRC, BIN, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(HERE)
raw = json.load(open(SRC))
steps = raw["steps"] if isinstance(raw, dict) and "steps" in raw else raw
D = json.loads(gzip.decompress(open(BIN, "rb").read()))
data = D.get("data", D)
meta = D.get("meta", {})
rmap = json.load(open(os.path.join(SCR, "_rename_map.json")))
alias_of = {}
for o, n in rmap.items():
    alias_of.setdefault(n, set()).add(o)

_day = {}


def dayfile(ymd):
    if ymd not in _day:
        p = os.path.join(CACHE, "%d.json" % ymd)
        try:
            _day[ymd] = {r[0]: r for r in json.load(open(p))} if os.path.exists(p) else {}
        except Exception:
            _day[ymd] = {}
    return _day[ymd]


def rclose(sym, names, ymd):
    df = dayfile(ymd)
    for nm in names:
        r = df.get(nm)
        if r and r[1]:
            return r[1]
    return None


cand = [s for s in steps if s["ymd"] >= 20020102 and not s.get("quant") and abs(s["applied"] - 1) > 0.03]
print("candidate applied steps (2002+, non-quant, |f-1|>0.03):", len(cand), flush=True)

out = []
t = 0
for s in cand:
    sym, ymd, f = s["sym"], s["ymd"], s["applied"]
    names = [sym, *sorted(alias_of.get(sym, ()))]
    d0 = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    ex = rclose(sym, names, ymd)
    pre = None
    for k in range(1, 91):
        v = rclose(sym, names, int((d0 - datetime.timedelta(days=k)).strftime("%Y%m%d")))
        if v:
            pre = v
            break
    post = []
    for k in range(1, 25):
        v = rclose(sym, names, int((d0 + datetime.timedelta(days=k)).strftime("%Y%m%d")))
        if v:
            post.append(v)
        if len(post) >= 8:
            break
    postmed = median(post[1:8]) if len(post) >= 3 else (median(post) if post else None)
    raw_step = (ex / pre) if (ex and pre) else None
    persist = (postmed / ex) if (ex and postmed) else None
    up = f >= 1.0
    # explained = the applied factor MATCHES the raw price move (real split/bonus/consolidation/crash);
    # phantom = a factor applied while the raw tape sat FLAT (raw_step ~ 1) and the factor disagrees.
    explained = (raw_step is not None) and (0.88 <= (f / raw_step) <= 1.14)
    flat = (raw_step is not None) and (0.85 <= raw_step <= 1.18)
    if raw_step is None:
        v = "REVIEW-no-pre"
    elif explained and persist is not None and 0.80 <= persist <= 1.25:
        v = "REAL"
    elif explained:
        v = "REAL-noholdcheck"
    elif flat and abs(f - 1) > 0.08:
        v = "PHANTOM"
    else:
        v = "REVIEW"
    out.append(
        {
            "sym": sym,
            "ymd": ymd,
            "applied": round(f, 4),
            "dir": "up" if up else "down",
            "raw_step": round(raw_step, 4) if raw_step else None,
            "persist": round(persist, 3) if persist else None,
            "pre": pre,
            "ex": ex,
            "verdict": v,
            "name": (meta.get(sym, {}) or {}).get("name", ""),
            "turnover": s.get("turnover"),
        }
    )
    t += 1
    if t % 2000 == 0:
        print("  %d/%d" % (t, len(cand)), flush=True)

byv = Counter(r["verdict"] for r in out)
json.dump(out, open(OUT, "w"))
print("=== verdicts ===", dict(byv))
ph = sorted([r for r in out if r["verdict"] == "PHANTOM"], key=lambda r: -(r["turnover"] or 0))
print(
    "\nPHANTOM total %d  (up %d / down %d)"
    % (len(ph), sum(r["dir"] == "up" for r in ph), sum(r["dir"] == "down" for r in ph))
)
print("top 60 PHANTOM by turnover:")
for r in ph[:60]:
    print(
        "  %-11s %d applied=%.3f %s raw_step=%s persist=%s pre=%s ex=%s  %s"
        % (r["sym"], r["ymd"], r["applied"], r["dir"], r["raw_step"], r["persist"], r["pre"], r["ex"], r["name"][:22])
    )
