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
"""ONE-TIME (idempotent) heal: null the ebit slots for adjudicated no-ebit filers, both files.

User decision 2026-08-16: "show nbfc and banks like screener do", then "go ahead with the sf_revop
data alignment" — the DATA now matches the coverage page: banking-format filers and screener-layout
lenders carry NO ebit, anywhere.

WHAT IT TOUCHES  slots 7 (ebitStd) and 8 (ebitCon) ONLY, for the symbols adjudicated in
  scripts/coverage_na_ledger.json['ebit'] (+ their FUND_ALIAS closure, both directions — a
  renamed lender's history under its old key is the same company). rev/op/pat/fin slots are
  asserted UNTOUCHED by count.

WHY BOTH FILES  scripts/revop_fundamentals.json is the accumulated store; docs/sf_revop.json is
  the web copy the 15-min cron upserts into. Healing only one leaves the other to disagree
  (feedback-two-files-one-quantity). Resurrection by rebuild/upsert is blocked separately by
  strip_lender_ebit() in build_revop.py, applied by every writer that computes ebit.

RUN TWICE  (feedback-a-heal-that-reapplies): the second pass must report 0 changes.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")


def lender_symbols():
    led = json.load(open(os.path.join(HERE, "coverage_na_ledger.json")))
    syms = {s for s, e in led.get("ebit", {}).items() if not s.startswith("_")}
    src = open(os.path.join(DOCS, "backtest-engine.js")).read()
    m = re.search(r"FUND_ALIAS\s*=\s*(\{.*?\})\s*;", src, re.DOTALL)
    alias = json.loads(re.sub(r"(\w+)\s*:", r'"\1":', m.group(1)).replace("'", '"')) if m else {}
    out = set(syms)
    for s in syms:
        if alias.get(s):
            out.add(alias[s])  # history stored under the old key
    for k, v in alias.items():
        if v in syms:
            out.add(k)  # old symbol still reachable in era rosters
    return out, syms


def heal(path, targets):
    d = json.load(open(path))
    before = [0] * 9
    for sym, rows in d.items():
        for c in rows.values():
            for i in range(min(9, len(c))):
                if i != 6 and c[i] is not None:
                    before[i] += 1
    changed = 0
    per = {}
    for sym in targets:
        rows = d.get(sym)
        if not rows:
            continue
        n = 0
        for c in rows.values():
            for i in (7, 8):
                if len(c) > i and c[i] is not None:
                    c[i] = None
                    n += 1
        if n:
            per[sym] = n
            changed += n
    after = [0] * 9
    for sym, rows in d.items():
        for c in rows.values():
            for i in range(min(9, len(c))):
                if i != 6 and c[i] is not None:
                    after[i] += 1
    # blast-radius assertion: ONLY slots 7/8 moved
    for i in (0, 1, 2, 3, 4, 5):
        assert before[i] == after[i], f"slot {i} changed in {path} — ABORT"
    if changed:
        json.dump(d, open(path, "w"), separators=(",", ":"))
    print(f"{os.path.basename(path)}: nulled {changed} ebit cells across {len(per)} symbols")
    for s, n in sorted(per.items(), key=lambda x: -x[1])[:12]:
        print(f"   {s:14s} {n:3d}")
    return changed


def main():
    targets, base = lender_symbols()
    print(f"ledger symbols {len(base)} -> with alias closure {len(targets)}")
    c1 = heal(os.path.join(HERE, "revop_fundamentals.json"), targets)
    c2 = heal(os.path.join(DOCS, "sf_revop.json"), targets)
    print(f"total nulled: {c1 + c2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
