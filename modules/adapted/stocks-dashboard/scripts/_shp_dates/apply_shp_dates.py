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
"""Phase 3a: build scripts/shp_sub_dates.json — the LEDGER of real SHP filing dates recovered
from BSE SHPQNewFormat — and (with --apply) write them into docs/shp_engine.json.

Dry-run by default, same convention as apply_redating.py / gate_1530.py.

WHAT IT WRITES. Only cells whose stored sub is the quarter-end+21d CONVENTION and for which BSE
publishes a real filing timestamp. A cell with a real stored date is NEVER touched here — the
store's own real dates carry a separate, larger defect (the §104 NSE-lag class, measured in the
pilot: RELIANCE Sep-2019 stored 2019-11-20 vs BSE's real 2019-10-19) and that is a separate,
scoped campaign, not a side effect of this one.

VISIBILITY RULE — 15:30 IST gate (USER DECISION 2026-08-23). A filing broadcast after the close
is only actionable the next session; 56.4% of real filings are (measured, 748 filings). This is
the same rule the fundamentals ann-dates use (gate_1530.py). It DIVERGES from the ~60k older SHP
cells, which store the raw broadcast date — deliberately: writing a date we have measured to be a
day early is the exact error class this campaign exists to remove. The divergence is logged here
and in PLAN_SHP_DATES so the follow-up sweep can converge the rest.

GUARDS (each from a measured failure, never speculative):
  * lag 0..120d — a "New" row can be a years-later RE-UPLOAD (TALWALKARS Sep-2021 carries
    filing_date_time 2026-06-29). Real lags measured over 748 filings: median 17d, max 47d.
  * revised-fallback rows are ACCEPTED but tagged: their timestamp is the revision, i.e. strictly
    LATER than the true first disclosure — conservative, never look-ahead.
  * never writes a date <= quarter end, never a future date.

Usage:  apply_shp_dates.py            # dry run -> shp_sub_dates.json + report
        apply_shp_dates.py --apply    # also rewrite docs/shp_engine.json
"""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import shp_dates as SD

LEDGER = os.path.join(SCRIPTS, "shp_sub_dates.json")
ENGINE = os.path.join(ROOT, "docs", "shp_engine.json")
MAX_LAG = 120


def lag_days(qe, d):
    a = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    b = datetime.date(d // 10000, (d // 100) % 100, d % 100)
    return (b - a).days


def main():
    apply = "--apply" in sys.argv
    shp = json.load(open(ENGINE))
    cal = SD.tdays()
    today = int(datetime.date.today().strftime("%Y%m%d"))

    fetched = {}
    for i in (0, 1):
        p = os.path.join(HERE, f"full_shard{i}.json")
        if os.path.exists(p):
            fetched.update(json.load(open(p)))
    print(f"fetched symbols: {len(fetched)}")

    reasons = collections.Counter()
    ledger, decisions = {}, []
    for sym, rows in shp.items():
        ent = fetched.get(sym)
        if not ent or ent.get("error"):
            continue
        res = {int(k): v for k, v in (ent.get("resolved") or {}).items()}
        for q in rows:
            if not (isinstance(q, list) and len(q) > 3):
                continue
            qe, sub = q[0], q[3]
            if qe < 20160101 or not sub or not SD.is_convention(qe, sub):
                continue  # only convention cells are in scope
            r = res.get(qe)
            if not r:
                reasons["no_api_row"] += 1
                continue
            raw, _mins = SD.ts_parts(r["ts"])
            if raw is None:
                reasons["unparseable_ts"] += 1
                continue
            L = lag_days(qe, raw)
            if not (0 <= L <= MAX_LAG):
                reasons["guard_lag"] += 1
                continue
            new, gated = SD.visible_date(r["ts"], cal)
            if new is None or new <= qe or new > today:
                reasons["guard_bounds"] += 1
                continue
            if new == sub:
                reasons["noop"] += 1
                continue
            reasons["write"] += 1
            ledger[f"{sym}|{qe}"] = {
                "sub": new,
                "ts": r["ts"],
                "src": r["src"],
                "gated_1530": gated,
                "was": sub,
                "prov": "bse:SHPQNewFormat filing_date_time",
            }
            decisions.append(
                {
                    "sym": sym,
                    "qe": qe,
                    "old": sub,
                    "new": new,
                    "delta": new - sub,
                    "gated": gated,
                    "src": r["src"],
                    "lag": L,
                }
            )

    print("=== decisions ===")
    for k in sorted(reasons):
        print(f"  {k:16s} {reasons[k]}")
    if decisions:
        earlier = sum(1 for d in decisions if d["new"] < d["old"])
        later = sum(1 for d in decisions if d["new"] > d["old"])
        gated = sum(1 for d in decisions if d["gated"])
        revsrc = sum(1 for d in decisions if d["src"] == "revised-fallback")
        lags = sorted(d["lag"] for d in decisions)
        print(f"  direction        earlier={earlier} later={later}")
        print(f"  15:30-gated      {gated} ({100 * gated / len(decisions):.1f}%)")
        print(f"  revised-fallback {revsrc}")
        print(f"  lag median {lags[len(lags) // 2]}d  p95 {lags[int(0.95 * len(lags))]}d  max {lags[-1]}d")
    json.dump(ledger, open(LEDGER, "w"), indent=0, sort_keys=True)
    print(f"\nledger -> {os.path.relpath(LEDGER, ROOT)} ({len(ledger)} entries)")

    if not apply:
        print("\n(dry run — pass --apply to rewrite docs/shp_engine.json)")
        return

    written = 0
    for sym, rows in shp.items():
        for q in rows:
            if not (isinstance(q, list) and len(q) > 3):
                continue
            e = ledger.get(f"{sym}|{q[0]}")
            if e and q[3] == e["was"]:
                q[3] = e["sub"]
                written += 1
    json.dump(shp, open(ENGINE, "w"), separators=(",", ":"))
    print(f"applied {written} cell writes -> docs/shp_engine.json")
    print("DONE.")


if __name__ == "__main__":
    main()
