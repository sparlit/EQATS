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
"""Phase 1 pilot: fetch SHPQNewFormat for a symbol sample, cache raw, and CALIBRATE against the
quarters where docs/shp_engine.json already holds a REAL (non-convention) date.

The calibration is the gate, not a formality (PLAN_SHP_DATES phase 1):
  * exact-match rate vs stored real dates >= 90%
  * ZERO pipeline-EARLIER-than-stored cases — an early date manufactures look-ahead, the one
    error class that is never acceptable. (Pipeline LATER than stored is merely conservative.)
It also tells us empirically whether the store's real dates follow the New-filing timestamp or
the revision timestamp — a question we deliberately did not answer by assumption.

Run: .venv/bin/python3 pilot.py [n_symbols]
"""
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SCRIPTS, "_staleness_fix"))
import contextlib

import fetch_and_match as m  # reuse its cookie-jar'd BSE getter
import shp_dates as SD

RAW = os.path.join(HERE, "raw_pilot.jsonl")
OUT = os.path.join(HERE, "pilot_results.json")
API = "https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode="


def main():
    n_syms = int(sys.argv[1]) if len(sys.argv) > 1 else 36
    shp = json.load(open(os.path.join(ROOT, "docs", "shp_engine.json")))
    by_id = json.load(open(os.path.join(SCRIPTS, "bse_scrips.json")))["by_id"]
    master = {}
    for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
        sid, cd = r.get("scrip_id"), r.get("SCRIP_CD")
        if sid and cd and sid not in master:
            with contextlib.suppress(TypeError, ValueError):
                master[sid] = int(cd)

    # target population: symbols carrying >=1 post-2016 CONVENTION cell
    targets = {}
    for sym, rows in shp.items():
        conv = [
            q[0]
            for q in rows
            if isinstance(q, list) and len(q) > 3 and q[0] >= 20160101 and SD.is_convention(q[0], q[3])
        ]
        if conv:
            targets[sym] = sorted(conv)
    syms = [s for s in sorted(targets, key=lambda s: -len(targets[s])) if (s in by_id or s in master)][:n_syms]
    print(f"target population: {len(targets)} symbols; pilot takes {len(syms)}")

    cal = SD.tdays()
    open(RAW, "w").close()
    results, stats = {}, collections.Counter()
    calib = {"exact": 0, "pipeline_earlier": 0, "pipeline_later": 0, "no_api_row": 0}
    earlier_examples, later_examples = [], []
    src_when_matched = collections.Counter()

    for i, sym in enumerate(syms, 1):
        sc = by_id.get(sym) or master.get(sym)
        try:
            table = json.loads(m.get(API + str(sc), timeout=30))["Table"]
        except Exception as e:
            print(f"  {sym}: FETCH FAIL {type(e).__name__}")
            stats["fetch_fail"] += 1
            continue
        with open(RAW, "a") as f:
            f.write(json.dumps({"sym": sym, "scripcode": sc, "table": table}, separators=(",", ":")) + "\n")
        resolved = SD.resolve_rows(table)

        # --- calibration against stored REAL dates (post-2016, non-convention) ---
        for q in shp.get(sym, []):
            if not (isinstance(q, list) and len(q) > 3):
                continue
            qe, sub = q[0], q[3]
            if qe < 20160101 or not sub or SD.is_convention(qe, sub):
                continue
            r = resolved.get(qe)
            if not r:
                calib["no_api_row"] += 1
                continue
            got, _g = SD.visible_date(r["ts"], cal)
            if got is None:
                calib["no_api_row"] += 1
            elif got == sub:
                calib["exact"] += 1
                src_when_matched[r["src"]] += 1
            elif got < sub:
                calib["pipeline_earlier"] += 1
                if len(earlier_examples) < 8:
                    earlier_examples.append((sym, qe, "stored", sub, "pipeline", got, r["src"], r["ts"]))
            else:
                calib["pipeline_later"] += 1
                if len(later_examples) < 8:
                    later_examples.append((sym, qe, "stored", sub, "pipeline", got, r["src"], r["ts"]))

        # --- the recoverable cells (post-2016 convention) ---
        fixes = []
        for qe in targets[sym]:
            r = resolved.get(qe)
            if not r:
                stats["target_no_api_row"] += 1
                continue
            got, gated = SD.visible_date(r["ts"], cal)
            if got is None:
                stats["target_unparseable"] += 1
                continue
            stored = next((q[3] for q in shp[sym] if q[0] == qe), None)
            if got == stored:
                stats["target_noop"] += 1
                continue
            fixes.append({"qe": qe, "old": stored, "new": got, "gated": gated, "src": r["src"], "ts": r["ts"]})
            stats["target_fix"] += 1
        results[sym] = {"scripcode": sc, "fixes": fixes}
        if i % 6 == 0:
            print(f"  ...{i}/{len(syms)}")
        time.sleep(0.3)

    json.dump(results, open(OUT, "w"), indent=1)
    tot = calib["exact"] + calib["pipeline_earlier"] + calib["pipeline_later"]
    rate = 100 * calib["exact"] / tot if tot else 0
    print()
    print("=== CALIBRATION vs stored REAL dates ===")
    print(f"  comparable cells      {tot}")
    print(f"  exact match           {calib['exact']}  ({rate:.1f}%)   GATE >= 90%")
    print(f"  pipeline EARLIER      {calib['pipeline_earlier']}   GATE == 0 (look-ahead risk)")
    print(f"  pipeline later        {calib['pipeline_later']}   (conservative, tolerable)")
    print(f"  no API row for cell   {calib['no_api_row']}")
    print(f"  src of matches        {dict(src_when_matched)}")
    for e in earlier_examples:
        print("   EARLIER:", e)
    for e in later_examples[:4]:
        print("   later  :", e)
    print()
    print("=== RECOVERY on the target (convention) cells ===")
    for k in sorted(stats):
        print(f"  {k:22s} {stats[k]}")
    print(f"  symbols with fixes: {sum(1 for v in results.values() if v['fixes'])}/{len(results)}")
    gate_ok = rate >= 90 and calib["pipeline_earlier"] == 0
    print()
    print("GATE:", "PASS" if gate_ok else "FAIL — do not proceed to phase 2")


if __name__ == "__main__":
    main()
