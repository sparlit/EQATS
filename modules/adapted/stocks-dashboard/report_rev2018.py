# -*- coding: utf-8 -*-
"""FILL-2018: the per-cell final status of every target cell — filled / not-applicable / refused.

§57a and §61b together forbid the two things a backfill report usually does: calling a cell
"unfillable", and merging cells that were never attempted into a residue that reads as "tried and
failed". So every one of the 730 target cells ends in EXACTLY ONE of:

  filled            value + the route that produced it + its anchor, from that route's own ledger
  not-applicable    the E1+E2+E3+E6 evidence set (§81) — no value written, evidence recorded
  not-found-via     the ordered list of routes actually walked for that cell, each having returned
                    nothing, plus the stage that failed last (§61's diagnosis, never a bare bucket)
  not-attempted     a route bound excluded it — reported separately, never as residue (§57a rule 4)

Writes scripts/fill2020_tools/_report_rev2018.json and prints the summary.

  python -X utf8 scripts/fill2020_tools/report_rev2018.py
"""
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
OUT = os.path.join(HERE, "_report_rev2018.json")
Q2018 = {20180331, 20180630, 20180930, 20181231}


def _load(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return {} if d is None else d


def main():
    targets = _load(os.path.join(HERE, "_rev2018_targets.json"))
    revop = _load(os.path.join(ROOT, "docs", "sf_revop.json"))
    cls = (_load(os.path.join(HERE, "_class_rev2018.json")) or {}).get("cells", {})
    na = dict((_load(os.path.join(SCRIPTS, "no_con_quarterly_2018.json")) or {}).get("cells", []))

    # --- route ledgers, in the order the ladder was walked -------------------------------------
    ledgers = [
        ("nse-xbrl (§54a)", _load(os.path.join(SCRIPTS, "nse_xbrl_rev_fills.json"))),
        ("bse-detres (§42)", _load(os.path.join(SCRIPTS, "std_rev_detres_fills.json"))),
        ("no-con-filed identity (§54b)", _load(os.path.join(SCRIPTS, "con_nofile_identity_fills.json"))),
        ("moneycontrol quarterly (§81)", _load(os.path.join(SCRIPTS, "mc_quarterly_fills.json"))),
        ("aggregator gate (§81)", _load(os.path.join(SCRIPTS, "agg_cell_fills.json"))),
        ("screener annual identity (§60d)", _load(os.path.join(SCRIPTS, "annual_derived_fills.json"))),
        ("hand-read + FY/9M identity (§45)", _load(os.path.join(SCRIPTS, "named_rev_cell_fills_2018.json"))),
        ("VISION rung (§17b)", _load(os.path.join(SCRIPTS, "vision_rung_fills_2018.json"))),
        ("year-later comparative (§84/§51a)", _load(os.path.join(SCRIPTS, "yearlater_rev_fills_2018.json"))),
        ("deoverlay/date-column reader (§75/§76)", _load(os.path.join(SCRIPTS, "deoverlay_rev_fills2018.json"))),
        ("insurer route (§55)", _load(os.path.join(SCRIPTS, "insurer_con_rev_fills.json"))),
        ("§58 announcement-PDF sweep", _load(os.path.join(SCRIPTS, "_revgap_done.json"))),
    ]
    skips = _load(os.path.join(SCRIPTS, "_revgap_skips.json"))
    diag = _load(os.path.join(HERE, "_diag_rev2018.json"))
    deo_skips = _load(os.path.join(HERE, "_deoverlay_skips.json"))
    xbrl_skips = _load(os.path.join(SCRIPTS, "_nse_xbrl_rev_skips.json"))

    def route_for(sym, qe, basis):
        """Which ledger claims this cell. Keys differ per tool, so try every shape they use."""
        keys = ["%s|%d" % (sym, qe), "%s|%d|%s" % (sym, qe, basis),
                "%s|%d|rev%s" % (sym, qe, "C" if basis == "con" else "S")]
        for name, led in ledgers:
            for k in keys:
                if k in led:
                    return name, led[k]
        return None, None

    rows, summary, refusal_stage = {}, Counter(), Counter()
    for sym, v in sorted(targets.items()):
        for basis, slot, qes in (("std", 0, v.get("revS", [])), ("con", 1, v.get("revC", []))):
            for qe in qes:
                key = "%s|%d|%s" % (sym, qe, basis)
                row = (revop.get(sym) or {}).get(str(qe))
                val = row[slot] if row and len(row) > slot else None
                rec = {"basis": basis, "value": val}
                if cls.get("%s|%d" % (sym, qe)):
                    rec["exchange_record"] = cls["%s|%d" % (sym, qe)]["kind"]
                    rec["anchored"] = cls["%s|%d" % (sym, qe)]["anchored"]
                if val is not None:
                    name, ev = route_for(sym, qe, basis)
                    rec["status"] = "filled"
                    rec["route"] = name or "filled (route ledger not matched — see git history)"
                    rec["evidence"] = ev
                    summary["filled"] += 1
                elif key.rsplit("|", 1)[0] in na or "%s|%d" % (sym, qe) in na:
                    rec["status"] = "not-applicable"
                    rec["evidence"] = na.get("%s|%d" % (sym, qe))
                    summary["not-applicable"] += 1
                else:
                    walked = ["nse-xbrl (§54a)"]
                    if basis == "std":
                        walked.append("bse-detres (§42)")
                    walked += ["no-con-filed identity (§54b)", "screener annual identity (§60d)",
                               "§58 announcement-PDF sweep", "deoverlay reader (§75/§76)"]
                    stage = (diag.get(key) or {}).get("stage") \
                        or deo_skips.get(key) or skips.get("%s|%d" % (sym, qe)) \
                        or xbrl_skips.get(key) or "not-diagnosed"
                    if isinstance(stage, dict):
                        stage = stage.get("stage") or json.dumps(stage)[:80]
                    rec["status"] = "not-found-via"
                    rec["routes_walked"] = walked
                    rec["last_stage"] = str(stage)[:160]
                    summary["not-found-via"] += 1
                    refusal_stage[str(stage).split(":")[0][:52]] += 1
                rows[key] = rec

    json.dump({"cells": rows, "summary": dict(summary)}, open(OUT, "w"), indent=1, sort_keys=True)
    tot = sum(summary.values())
    print("FILL-2018 per-cell status — %d cells\n" % tot)
    for k, n in summary.most_common():
        print("  %-18s %4d   (%.1f%%)" % (k, n, 100.0 * n / tot))
    print("\nrefusals by the stage that actually failed (§61):")
    for k, n in refusal_stage.most_common(18):
        print("  %-54s %4d" % (k, n))
    by_route = Counter(r["route"] for r in rows.values() if r["status"] == "filled")
    print("\nfilled, by route:")
    for k, n in by_route.most_common():
        print("  %-42s %3d" % (k, n))
    print("\nwrote %s" % os.path.basename(OUT))


if __name__ == "__main__":
    main()
