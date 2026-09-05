# -*- coding: utf-8 -*-
"""CALIBRATE the MC deep feed on the 257 cells §109 already adjudicated to a document.

Each landed heal has a KNOWN as-filed value (`fixed`) and a KNOWN later-vintage value (`was`).
If MC serves the as-filed vintage it should sit on `fixed`. Anything else — sitting on `was`, or on
neither — is measured here rather than assumed.   memory: feedback-calibrate-gate-by-holdout
"""
import json, os, sys
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
AG._get = lambda host, url, pace, site, key, **kw: AG._cached(site, key, 10 ** 9)


def near(a, b, ab=0.35, rl=0.005):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def main():
    # read the LANDED §108 heals out of the committed ledger, not a scratch file: the scratch
    # proposals file is rewritten to empty once its heals are applied, so a calibration keyed to it
    # silently measures nothing on a re-run.
    led = json.load(open(os.path.join(HERE, "fund_cell_fix.json")))["fixes"]
    props = {"proposals": [f for f in led if "vintage108 sweep" in str(f.get("found", ""))]}
    per, cnt, ex = {}, Counter(), []
    for p in props["proposals"]:                       # fund_cell_fix only: npStd / npCon
        sym, qe, basis = p["sym"], int(p["qe"]), p["basis"]
        ck = (sym, basis)
        if ck not in per:
            try:
                per[ck] = AG.mc_quarters(sym, basis == "con")[0]
            except Exception:
                per[ck] = {}
        row = (per[ck] or {}).get(qe)
        if not row:
            cnt["no MC reading"] += 1
            continue
        mc = row.get("pat_own") if (basis == "con" and row.get("pat_own") is not None) else row.get("pat_total")
        if near(mc, p["fixed"]):
            cnt["MC == the AS-FILED value (heal target)"] += 1
        elif near(mc, p["was"]):
            cnt["MC == the RESTATED value (what we removed)"] += 1
            ex.append((sym, qe, basis, p["was"], p["fixed"], mc))
        else:
            cnt["MC == neither"] += 1
            ex.append((sym, qe, basis, p["was"], p["fixed"], mc))
    print("MC calibrated on %d §109 heals with a known as-filed answer:" % len(props["proposals"]))
    tot = sum(v for k, v in cnt.items() if k != "no MC reading")
    for k, n in cnt.most_common():
        print("   %-46s %4d %s" % (k, n, "" if k == "no MC reading" else "(%.1f%% of reached)" % (100.0 * n / tot)))
    print("\nthe cells where MC is NOT on the as-filed value:")
    for e in ex[:25]:
        print("   %-13s %-9s %-4s was=%-10s fixed=%-10s mc=%s" % e)


if __name__ == "__main__":
    main()
