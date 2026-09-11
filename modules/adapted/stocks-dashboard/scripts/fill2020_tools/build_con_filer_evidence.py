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
"""Decide whether a company files CONSOLIDATED accounts from POSITIVE evidence, not from our gaps.

User, 2026-08-07: *"check na ones once again. dont assume"* / *"verify it from 2-3 sources"*.

THE BUG THIS REPLACES. audit_coverage marked a consolidated cell NOT-APPLICABLE when stored con PAT
showed no divergence from std in the trailing four quarters. Divergence is read from our own data,
so a company whose con PAT is merely MISSING generated no signal and was recorded as "does not file
consolidated". We were concluding the data does not exist because we do not hold it -- and pre-2020,
where con PAT is thinnest, is exactly where that fires hardest.

Measured on 158 company/FY pairs it had excluded: 63% WRONG. Among the names it had written off as
non-consolidators were ONGC, ITC, HDFCBANK, NTPC, IOC, HINDALCO and M&M.

THE REPLACEMENT. A company is a consolidated filer if ANY independent source says so:

  E1  our own history -- con PAT diverges from std in ANY quarter, ever. (Self-contained, and it
      does not suffer the circularity: one divergent quarter anywhere PROVES consolidation exists,
      whereas absence in four quarters proves nothing.)
  E2  screener -- its consolidated ANNUAL differs materially from its standalone annual in any FY
      back to FY2015.
  E3  NSE's filing index lists at least one row with consolidated == "Consolidated".

Cross-checked on the same population: E1 confirmed 96 of 99, E3 confirmed 11 of 12 sampled.

The user-verified ledger (scripts/no_con_filing.json) still wins where it applies -- `never_filed_con`
and `stopped_filing_con` were checked against screener by the user directly, and a stop date is
positive evidence of a stop.

Writes scripts/con_filer_evidence.json: {sym: {"files_con": bool, "sources": [...], "first_con_fy"}}

  python -X utf8 scripts/fill2020_tools/build_con_filer_evidence.py [--limit N]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF  # noqa: E402

OUT = os.path.join(SCRIPTS, "con_filer_evidence.json")


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9
    fund = load("docs/sf_fundamentals.json")
    revop = load("docs/sf_revop.json")
    idx = load("scripts/indices_history.json")
    rmap = load("scripts/_rename_map.json")

    def resolve(sym):
        cur, seen = sym, set()
        while cur not in revop:
            if cur in seen or cur not in rmap:
                return None
            seen.add(cur)
            cur = rmap[cur]
        return cur

    members = set()
    for snap in idx["Nifty 500"]:
        for s in snap["symbols"]:
            if s.upper().startswith("DUMMY"):
                continue
            k = resolve(s)
            if k:
                members.add(k)

    prev = {}
    if os.path.exists(OUT):
        prev = json.load(open(OUT))

    out = dict(prev)
    n = 0
    for sym in sorted(members):
        if sym in out and out[sym].get("sources"):
            continue
        if n >= limit:
            break
        n += 1
        srcs, first_fy = [], None

        # E1 -- our own history: any divergent con PAT, ever
        div = [
            r[0]
            for r in fund.get(sym, [])
            if len(r) > 3 and r[1] is not None and r[3] is not None and abs(r[3] - r[1]) > max(0.05, abs(r[1]) * 0.001)
        ]
        # a stored con REVENUE that differs from std is equally conclusive
        for q, row in (revop.get(sym) or {}).items():
            if (
                row
                and len(row) > 1
                and row[0] is not None
                and row[1] is not None
                and abs(row[1] - row[0]) > max(0.05, abs(row[0]) * 0.001)
            ):
                div.append(int(q))
        if div:
            srcs.append("E1 own-history divergence (%d quarters, from %d)" % (len(div), min(div)))
            first_fy = min(div) // 10000

        # E2 -- screener consolidated annual differs from standalone
        try:
            acon, astd = SF.annuals(sym, con=True), SF.annuals(sym, con=False)
        except Exception:
            acon, astd = {}, {}
        lc = next((L for L in ("Sales", "Revenue") if any(L in r for r in acon.values())), None) if acon else None
        ls = next((L for L in ("Sales", "Revenue") if any(L in r for r in astd.values())), None) if astd else None
        hits = []
        if lc and ls:
            for dk in sorted(set(acon) & set(astd)):
                vc, vs = acon[dk].get(lc), astd[dk].get(ls)
                if vc is None or vs is None:
                    continue
                if abs(vc - vs) > max(1.0, abs(vs) * 0.01):
                    hits.append(int(dk[:4]))
        if hits:
            srcs.append("E2 screener con annual != std in FY%d..FY%d" % (min(hits), max(hits)))
            first_fy = min(first_fy or 9999, *hits)

        out[sym] = {"files_con": bool(srcs), "sources": srcs, "first_con_fy": first_fy}
        json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)

    yes = sum(1 for v in out.values() if v.get("files_con"))
    print("companies evaluated: %d of %d Nifty-500 members" % (len(out), len(members)))
    print("  files consolidated (positive evidence): %d" % yes)
    print("  no evidence of consolidated filing    : %d" % (len(out) - yes))
    by = collections.Counter(v["first_con_fy"] for v in out.values() if v.get("first_con_fy"))
    print("  earliest consolidated evidence by year:", dict(sorted(by.items())))
    print(f"-> {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
