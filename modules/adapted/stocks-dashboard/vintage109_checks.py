# -*- coding: utf-8 -*-
"""Pre-land checks on the by-product heal set. Every one of these has burned a past campaign."""
import json, os, re, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import _nse_archive_revop as NA  # noqa: E402
import agg_sources as AG  # noqa: E402
# NO_PERSIST — see vintage109_mc_probe.py. mc_id() writes its result to _agg_ids_mc.json, and
# under the cache-only stub below an offline miss would be persisted as `"SYM": null`, so a later
# ONLINE run skips fetching it. Redirect the write; never neuter json.dump (that truncates the file).
AG._MC_IDS = json.load(open(AG._MC_IDS_PATH, encoding="utf-8"))
AG._MC_IDS_PATH = os.path.join(HERE, "_vintage109_mc_ids_scratch.json")
AG._get = lambda host, url, pace, site, key, **kw: AG._cached(site, key, 10 ** 9)
PAGES = os.path.join(HERE, "_vintage108_nse_pages")
MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def near(a, b, ab=0.35, rl=0.005):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def main():
    a = json.load(open(os.path.join(HERE, "_vintage109_adjud.json")))["cells"]
    heals = [r for r in a.values() if r["verdict"] == "HEAL"]
    idx = {}
    for fn in os.listdir(PAGES):
        m = re.match(r"financial_res_(.+)_(\d+)\.html$", fn)
        if m:
            idx[m.group(2)] = os.path.join(PAGES, fn)
    fails = Counter()

    # ---- 1. the page must NAME this company, this period, this basis --------------
    for r in heals:
        f = idx.get(str(r["nse_seq"]))
        if not f:
            fails["page-not-cached"] += 1
            r["_chk"] = "page-not-cached"
            continue
        meta, _ = NA.parse_detail(open(f, encoding="utf-8", errors="replace").read())
        per = meta.get("Period Ended") or ""
        m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", per)
        pqe = int(m.group(3)) * 10000 + MON[m.group(2)] * 100 + int(m.group(1)) if m else None
        want = "Consolidated" if r["basis"] == "con" else "Non-Consolidated"
        if pqe != r["qe"]:
            fails["period-mismatch"] += 1
            r["_chk"] = "period %s != qe" % per
        elif (meta.get("Consolidated / Non-Consolidated") or "") != want:
            fails["basis-mismatch"] += 1
            r["_chk"] = "basis %s != %s" % (meta.get("Consolidated / Non-Consolidated"), want)
        elif meta.get("Symbol") and meta["Symbol"].strip().upper() not in (
                r["sym"].upper(), r["sym"].upper().replace("&", "_").replace("-", "_")):
            fails["symbol-mismatch"] += 1
            r["_chk"] = "page Symbol=%s" % meta.get("Symbol")
        else:
            r["_chk"] = "ok"

    # ---- 2. MC con feed must not be a standalone fallback (§ aggregator-con-fallback)
    percon, perstd = {}, {}
    for r in heals:
        if r["basis"] != "con":
            continue
        s = r["sym"]
        if s not in percon:
            percon[s] = AG.mc_quarters(s, True)[0]
            perstd[s] = AG.mc_quarters(s, False)[0]
        c = (percon[s] or {}).get(r["qe"]) or {}
        d = (perstd[s] or {}).get(r["qe"]) or {}
        cv = c.get("pat_own", c.get("pat_total"))
        dv = d.get("pat_total")
        if cv is not None and dv is not None and abs(cv - dv) < 0.005:
            fails["mc-con-equals-mc-std (unresolved)"] += 1
            r["_chk_mc"] = "mc con == mc std (%.2f) — cannot tell the bases apart" % cv
        else:
            r["_chk_mc"] = "ok (mc con %s vs mc std %s)" % (cv, dv)

    # ---- 3. the target must not be a power-of-ten step off the store (unit trap, §74)
    for r in heals:
        t, s = r["nse_pat"], r["stored"]
        if t and s and any(abs(s / t - p) <= 0.02 * p for p in (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)):
            fails["target-is-a-power-of-ten-step"] += 1
            r["_chk_scale"] = "store/target = %.4f" % (s / t)

    # ---- 4. no cell may already carry a heal in either ledger ---------------------
    seen = set()
    for lg, key in (("fund_cell_fix.json", ("std", "con")), ("revop_cell_fix.json", None)):
        d = json.load(open(os.path.join(HERE, lg)))
        for f in (d["fixes"] if isinstance(d, dict) else d):
            seen.add((f["sym"], str(f["qe"]), f["basis"]))
    for r in heals:
        if (r["sym"], str(r["qe"]), r["basis"]) in seen:
            fails["already-in-a-ledger"] += 1
            r["_chk_dup"] = "already healed"

    print("PRE-LAND CHECKS over %d heals" % len(heals))
    print("  failures: %s" % (dict(fails) or "NONE"))
    for r in heals:
        for k in ("_chk", "_chk_mc", "_chk_scale", "_chk_dup"):
            v = r.get(k)
            if v and v != "ok" and not str(v).startswith("ok "):
                print("   %-13s %-9s %-4s  %s: %s" % (r["sym"], r["qe"], r["basis"], k, v))
    json.dump({"_doc": "§109e by-product adjudication (checked)", "cells": a},
              open(os.path.join(HERE, "_vintage109_adjud.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
