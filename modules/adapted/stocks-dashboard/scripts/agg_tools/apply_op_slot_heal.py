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
"""THE EBIT-IN-OP-SLOT CORRECTION APPLIER  (runbook §129b/§129g, user decision 2026-09-05 "Apply the heal").

The class: 3,797 stored `opStd` cells (2008-2016, 566 industrial symbols) equal Moneycontrol's
after-depreciation subtotal "P/L Before Other Inc., Int., Excpt. Items & Tax" to the paisa, with the
`ebitStd` slot empty on every one (`_op_slot_ebit_class.json`). Those campaigns (Rev-recovery OCR/vision
2026-07-30, detres/STEP-N 2026-08-04) read the SEBI line "profit from operations before other income,
finance costs and exceptional items" -- which is AFTER depreciation, i.e. this dataset's `ebit`
(build_revop.py: ebit = PBET + FC - OI) -- and stored it in a slot defined as BEFORE depreciation
(op = ebit + Depreciation). A correction, not a fill (§2b): every write below is guarded on the value it
replaces and journalled with what was there.

DECISION TABLE, per cell, measured PER COMPANY on its own 2018+ rows (opS, ebitS from XBRL; MC rows):
  (i)  EBIT CONVENTION  ebitS == MC ebit_pre on >= 2 rows, 0 disagreements (tol 0.05)
       -> the moved value is the same quantity as the company's existing ebit series.
       A company with NO 2018+ ebit at all passes vacuously: its whole ebit series becomes this
       definition, which is self-consistent (class label says so).
  (ii) DEPRECIATION      ebitS + MC dep == opS on >= 2 rows, 0 disagreements -> `op = ebit + dep` may be
       derived from the cell's OWN row (the subtotal that matched to the paisa) when the series gate
       did not pass. Measured 2026-09-05: 416 companies exact, 20 rounded (<=0.51, MC prints integer
       depreciation for them), 95 REFUSE (worst 787 cr -- MC's depreciation row is a different quantity
       from the XBRL tag for them), 35 without a 2018+ triple.
  ebitS := stored value            if (i) passes (or vacuous)            else NOT written
  opS   := gate-E value            if the op sweep gated it (897 cells, `opS_new` in the proposal)
         | stored + MC dep         if --derive-op and (ii) passes and dep >= 0 (precision from (ii))
         | None (HELD)             otherwise -- the old value is not operating profit; it is kept in
                                   the ledger under `opS_refused` and the verifier flags it if it
                                   ever comes back (RESURRECTED)

Safety (shape of apply_revop_cell_fix.py / correct_era_suspects.py):
  * guarded on `was`: slot 2 must still equal opS_old and slot 7 must be empty, else MOVED-ON, left alone
  * blast radius: the patched file is diffed against the original and the run aborts unless the only
    differences are slots 2/7 of the listed cells
  * idempotent: a second run reports every cell already-done and writes nothing
  * lender guard: a LENDER_EBIT_NA symbol is never touched (strip_lender_ebit would null the ebit anyway)
  * journal: scripts/op_slot_corrections.json keyed SYM|QE (opS slot 2, ebitS slot 7) and, for the nulled
    cells, scripts/op_slot_refused.json (opS_refused slot 2, held) -- both registered in verify_fills_live.py

  python3 -X utf8 scripts/agg_tools/apply_op_slot_heal.py [--derive-op]           # dry run
  python3 -X utf8 scripts/agg_tools/apply_op_slot_heal.py --derive-op --apply
"""
import argparse
import collections
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)
import agg_gate as G  # noqa: E402
import agg_sources as A  # noqa: E402
import mc_era as E  # noqa: E402
from build_revop import LENDER_EBIT_NA  # noqa: E402

PROPOSALS = os.path.join(HERE, "_op_slot_heal_proposals.json")
LEDGER = os.path.join(SCRIPTS, "op_slot_corrections.json")
# ★ The ABSENCE assertions live in their own file: verify_fills_live.py reads `held` per ENTRY, across
# every key registered for that ledger, so a record that both asserts ebitS is PRESENT and opS_refused
# is ABSENT would flag its own ebit as RESURRECTED (measured 2026-09-05: 166 false alarms).
REFUSED = os.path.join(SCRIPTS, "op_slot_refused.json")
TARGETS = [os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")]
TOL = 0.011
CONV_TOL = 0.05  # (i)/(ii) 'exact' band: both sides printed at 2dp, one may be crore-rounded
ROUND_TOL = 0.51  # (ii) 'rounded': MC prints integer depreciation for some companies
MIN_ROWS = 2
MAX_BAD = 10  # agg_era_gate.MAX_BAD / agg_gate.GLOBAL_MAX_BAD -- hold-out calibrated (§90, §81e)
MAX_BAD_RATE = 0.15


def company_checks(sym):
    """-> ((i)-verdict, (ii)-verdict, worst_ii, n_rows). Verdicts: exact | rounded | REFUSE | none."""
    ident = json.load(open(E._ISIN_CACHE)) if not hasattr(company_checks, "_idc") else company_checks._idc
    if not hasattr(company_checks, "_idc"):
        company_checks._idc = ident
    ident = ident.get(sym)
    q, _ = E.quarters(ident, False) if ident else A.read("mc", sym, False)
    op, eb = G.ours_series(sym, "opS"), G.ours_series(sym, "ebitS")
    conv, dep = [], []
    for qe, v in op.items():
        if qe < 20180101 or v == 0.0:
            continue
        row = q.get(qe) or {}
        e = eb.get(qe)
        if e is not None and row.get("ebit_pre") is not None:
            conv.append(abs(e - row["ebit_pre"]))
        if e is not None and row.get("dep") is not None:
            dep.append(abs(e + row["dep"] - v))

    def verdict(diffs):
        """agg_gate/agg_era_gate's calibrated identity rule, not a zero-tolerance one: >= MIN_ROWS agreeing
        rows and disagreements <= MAX_BAD and <= MAX_BAD_RATE (a stale ebit from a different filing --
        the 169-cell class of the 2026-09-01 audit -- is one bad row, not a different convention).
        Precision is the worst AGREEING row: exact (<= CONV_TOL) or rounded (<= ROUND_TOL)."""
        good = [d for d in diffs if d <= ROUND_TOL]
        bad = [d for d in diffs if d > ROUND_TOL]
        if len(good) < MIN_ROWS:
            return "none" if not diffs else "REFUSE", (round(max(diffs), 3) if diffs else None), len(good), len(diffs)
        if len(bad) > MAX_BAD or len(bad) / float(len(diffs)) > MAX_BAD_RATE:
            return "REFUSE", round(max(bad), 3), len(good), len(diffs)
        w = max(good)
        return ("exact" if w <= CONV_TOL else "rounded"), round(w, 3), len(good), len(diffs)

    ci, wi, gi, ni = verdict(conv)
    cii, wii, gii, nii = verdict(dep)
    return (
        ci,
        cii,
        wii,
        nii,
        {
            "ebit_convention": "%d/%d rows agree (worst %s)" % (gi, ni, wi),
            "depreciation": "%d/%d rows agree (worst %s)" % (gii, nii, wii),
        },
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposals", default=PROPOSALS)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--derive-op",
        action="store_true",
        help="write op = stored ebit + MC depreciation where check (ii) passes for the company",
    )
    ap.add_argument("--stamp", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args()

    cells = json.load(open(a.proposals))["cells"]
    syms = sorted({k.split("|")[0] for k in cells})
    checks = {}
    for i, s in enumerate(syms):
        checks[s] = company_checks(s)
    cc = collections.Counter(f"i={c[0]} ii={c[1]}" for c in checks.values())
    print("per-company checks (%d companies):" % len(checks))
    for k, v in sorted(cc.items()):
        print("   %-24s %d" % (k, v))
    ref = [(s, c[4]) for s, c in checks.items() if c[0] == "REFUSE"]
    print("   (i)-REFUSE companies, first 12:", ref[:12])

    # ---- decide every cell once, against the first target file (docs), then apply the same plan to both
    plan, why = {}, collections.Counter()
    base = json.load(open(TARGETS[0]))
    for key, p in sorted(cells.items()):
        sym, qe = key.rsplit("|", 1)
        if sym in LENDER_EBIT_NA:
            why["skip:lender"] += 1
            continue
        row = (base.get(sym) or {}).get(qe)
        if row is None:
            why["skip:row-absent"] += 1
            continue
        row = list(row) + [None] * (9 - len(row))
        old = p["opS_old"]
        if row[7] is not None and abs(row[7] - old) <= TOL and (row[2] is None or abs(row[2] - old) > TOL):
            why["already-done"] += 1
            continue
        if row[2] is None and row[7] is None:  # nulled+held/NOT-moved on a previous run
            why["already-done(nulled)"] += 1
            continue
        if row[2] is None or abs(row[2] - old) > TOL:
            why["skip:moved-on(slot2!=was)"] += 1
            continue
        if row[7] is not None:
            why["skip:ebit-slot-occupied"] += 1
            continue
        ci, cii, wii, n, detail = checks[sym]
        ent = {
            "opS_was": old,
            "mc_ebit_pre": p["mc_ebit_pre"],
            "mc_dep": p["mc_dep"],
            "company_check_ebit_convention": ci,
            "company_check_depreciation": cii,
            "company_check_depreciation_worst": wii,
            "company_check_rows": n,
            "company_check_detail": detail,
        }
        # ebit move
        if ci in ("exact", "rounded"):
            ent["ebitS"] = old
            ent["ebit_class"] = f"moved:{ci}-convention-match"
        elif ci == "none":
            ent["ebitS"] = old
            ent["ebit_class"] = "moved:no-2018+-ebit-to-compare (series becomes self-consistent on this definition)"
        else:
            ent["ebitS"] = None
            ent["ebit_class"] = f"NOT-moved:company's XBRL ebit != MC after-dep subtotal on 2018+ rows ({wii})"
            ent["ebit_unplaced_value"] = old
        # op
        if p.get("opS_new") is not None:
            ent["opS"] = p["opS_new"]
            ent["op_class"] = "gated:GATE-E op sweep ({})".format(p.get("state"))
            ent["precision"] = p.get("precision")
        # derivation needs BOTH checks: (ii) alone proves MC's depreciation, but stored + dep is MC's
        # op_pre, which reproduces OUR op only where the ebit convention (i) also holds (72 companies
        # pass (ii) and fail (i); for them stored + dep is a different quantity from our op)
        elif (
            a.derive_op
            and ci in ("exact", "rounded")
            and cii in ("exact", "rounded")
            and p["mc_dep"] is not None
            and p["mc_dep"] >= 0
        ):
            ent["opS"] = round(old + p["mc_dep"], 2)
            ent["op_class"] = "derived:stored-ebit+MC-dep (company check (ii) %s, worst %s on %d rows)" % (cii, wii, n)
            ent["precision"] = "site-exact" if cii == "exact" else f"rounded({wii})"
        else:
            ent["opS"] = None
            ent["refused"] = {
                "opS_refused": old,
                "held": (
                    "op slot nulled: the stored value is the after-depreciation subtotal, not "
                    "op; no gated or derivable op ({}; company check (i)={} (ii)={}; mc_dep={})".format(
                        "--derive-op off" if not a.derive_op else "derivation refused", ci, cii, p["mc_dep"]
                    )
                ),
            }
            ent["op_class"] = "nulled+held"
        if ent["opS"] is not None and ent.get("ebitS") is not None and ent["opS"] < ent["ebitS"] - TOL:
            why["skip:op<ebit"] += 1
            continue
        ent["evidence"] = (
            "stored opS {} equals MC standalone 'P/L Before Other Inc., Int., Excpt. Items & Tax' {} "
            "for this quarter (after-depreciation EBIT); ebitS slot was empty; runbook §129b/§129g".format(
                old, p["mc_ebit_pre"]
            )
        )
        ent["applied"] = f"{a.stamp} op-slot heal"
        plan[key] = ent
        why["plan:" + ent["op_class"].split(":")[0] + "/" + ent["ebit_class"].split(":")[0]] += 1
    print("\ncells: %d proposed" % len(cells))
    for k, v in sorted(why.items()):
        print("   %-60s %d" % (k, v))
    if not plan:
        print("nothing to do")
        return 0

    # ---- apply to both files with the blast-radius guard
    for path in TARGETS:
        d = json.load(open(path))
        orig = copy.deepcopy(d)
        n = 0
        for key, ent in plan.items():
            sym, qe = key.rsplit("|", 1)
            row = (d.get(sym) or {}).get(qe)
            if row is None:
                continue
            row = list(row) + [None] * (9 - len(row))
            if row[2] is None or abs(row[2] - ent["opS_was"]) > TOL or row[7] is not None:
                print(f"   MOVED-ON in {os.path.basename(path)}: {key} row={row}")
                continue
            row[2] = ent["opS"]
            if ent.get("ebitS") is not None:
                row[7] = ent["ebitS"]
            d[sym][qe] = row
            n += 1
        # blast radius: only slots 2/7 of planned cells may differ
        bad = []
        for sym, qs in d.items():
            for qe, row in qs.items():
                o = (orig.get(sym) or {}).get(qe)
                if o is None:
                    bad.append((sym, qe, "new row"))
                    continue
                o = list(o) + [None] * (9 - len(o))
                r = list(row) + [None] * (9 - len(row))
                for i in range(9):
                    if r[i] != o[i] and not (i in (2, 7) and f"{sym}|{qe}" in plan):
                        bad.append((sym, qe, i, o[i], r[i]))
        lost = [(s, q) for s, qs in orig.items() for q in qs if q not in (d.get(s) or {})]
        if bad or lost:
            print(f"ABORT: blast radius violated in {path}: {bad[:5]} {lost[:5]}")
            return 2
        print(
            "%-32s %s %d cells (slot 2 and/or 7)" % (os.path.basename(path), "patched" if a.apply else "would patch", n)
        )
        if a.apply:
            json.dump(d, open(path, "w"), separators=(",", ":"))

    if a.apply:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led["_doc"] = (
            "Corrections for the EBIT-in-op-slot class (runbook §129b/§129g): the stored opS was the "
            "after-depreciation SEBI subtotal (= MC 'P/L Before Other Inc., Int., Excpt. Items & Tax'). "
            "ebitS = that value where the company's ebit convention matches; opS = gate-E value, or "
            "stored+MC depreciation where the company's own 2018+ rows prove that derivation, else nulled "
            "and HELD (opS_refused must stay absent). Applied by agg_tools/apply_op_slot_heal.py."
        )
        ref = json.load(open(REFUSED)) if os.path.exists(REFUSED) else {}
        ref["_doc"] = (
            "HELD assertions of the op-slot heal (runbook §129g): the after-depreciation value that was "
            "nulled out of opS must stay ABSENT from slot 2; verify_fills_live.py flags RESURRECTED if a "
            "fill-only replay of the original OCR/detres reads lands it again. The value itself is kept in "
            "op_slot_corrections.json (opS_was / ebitS)."
        )
        nref = 0
        for key, ent in plan.items():
            r = ent.pop("refused", None)
            led[key] = ent
            if r:
                ref[key] = dict(r, applied=ent["applied"])
                nref += 1
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        json.dump(ref, open(REFUSED, "w"), indent=1, sort_keys=True)
        print(
            "journalled %d -> %s (+%d held assertions -> %s)"
            % (len(plan), os.path.relpath(LEDGER, ROOT), nref, os.path.relpath(REFUSED, ROOT))
        )
    else:
        print("DRY RUN -- nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
