# -*- coding: utf-8 -*-
"""screener.in as a SECOND, INDEPENDENT reader for op / ebit  (runbook §57 rung 3b, §60).

Why a separate script rather than a fourth site in agg_sources.READERS: Moneycontrol, Trendlyne and
Tickertape are ONE vendor with different row cuts (§81c) -- two of them agreeing is one reader
counted twice. screener.in is the genuinely independent axis, and it is independent in its PRINT
PRECISION too, which is exactly what agg_gate cannot express: its tolerances (EXACT_ABS 0.006,
ROUND_ABS 0.02) are measured off MC's two-decimals-of-a-crore. Screener prints CRORE-ROUNDED
INTEGERS. Measured 2026-08-12 against our own stored series:

    ATUL std op  ours 185.19 / 193.67 / 163.05 / 167.78   screener 185 / 194 / 163 / 168
    UNOMINDA con ours 407.71 / 482.37 / 456.99 / 526.71   screener 408 / 482 / 457 / 527

Every difference is under half a crore -- print rounding, not a different quantity. Feed that series
to agg_gate and every anchor reads as a disagreement; feed it a 1.0-crore floor and the floor becomes
the defect, which is the §81e lesson in reverse.

THE ROWS (Gate D -- proven against our own stored values, never assumed):
    op   <- "Operating Profit"
    ebit <- "Operating Profit" - "Depreciation"
build_revop.py defines ebit as after-depreciation operating profit (ebit = PBET + FinanceCosts -
OtherIncome), and op as Trendlyne's paisa-matched "Oper Profit"; the two differ by exactly the
depreciation line, which screener prints separately.

★ THE MAGNITUDE GUARD, AND WHY IT IS THE WHOLE POINT. A +-0.5 crore rounding is nothing on a 500
crore operating profit and is the entire number on a small one: WESTLIFE standalone stores op of
-0.07 / -0.21 / -0.14 crore against screener's -0.12 / -0.24 / -0.17, i.e. 71%, 14%, 21% "error"
from rounding alone. §81e records the same trap costing a holding company a false 13/16 agreement.
So a cell is only written when its own magnitude makes the print unit immaterial (MIN_MAGNITUDE),
and every fill is labelled `screener-rounded(<unit>)` -- §60e: a labelled approximation beats a
hole, an UNlabelled one is a lie.

Output is a proposal ledger in apply_agg_fills.py's shape; this script writes nothing itself.

  python3 -X utf8 scripts/agg_tools/screener_opebit.py --cells /tmp/open.json --out /tmp/sc.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
from screener_fetch import quarters                                    # noqa: E402

SLOT = {"opS": 2, "opC": 3, "ebitS": 7, "ebitC": 8}
OTHER = {"opS": "opC", "opC": "opS", "ebitS": "ebitC", "ebitC": "ebitS"}

# Screener prints whole crore, so a matched anchor can legitimately sit half a unit away; ebit is a
# DIFFERENCE of two rounded rows, so its worst case is a full unit. Anything past that is a real
# disagreement, not presentation.
UNIT = {"op": 0.51, "ebit": 1.01}
EXACT_ABS = 0.02          # both sides landed on the same printed figure
MIN_ANCHORS = 2           # §60c, unchanged
LOCAL_Q = 6
NEAR_Q = 4
GLOBAL_MAX_BAD = 0.15
# the print unit must be immaterial to the cell being written: 0.51/50 ~ 1%, 1.01/50 ~ 2%
MIN_MAGNITUDE = 50.0


def qidx(qe):
    return (qe // 10000) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[(qe // 100) % 100]


def ours_series(REV, sym, field):
    d = REV.get(sym) or {}
    i = SLOT[field]
    return {int(q): v[i] for q, v in d.items() if v and len(v) > i and v[i] is not None}


def value_of(row, field):
    op = row.get("Operating Profit")
    if op is None:
        return None
    if field.startswith("op"):
        return op
    dep = row.get("Depreciation")
    return None if dep is None else round(op - dep, 2)


def agree(mine, theirs, unit):
    d = abs(mine - theirs)
    if d <= EXACT_ABS:
        return "exact"
    return "rounded" if d <= unit else "no"


def gate(series, ours, qe, field):
    """series = {qe_int: screener row}. Same shape of test as agg_gate.check_series, with the
    tolerance taken from screener's OWN print precision rather than Moneycontrol's."""
    unit = UNIT["op" if field.startswith("op") else "ebit"]
    ti = qidx(qe)
    matched = local = checked = 0
    worst = 0.0
    bad_local, bad_far, our_zeros = [], [], []
    for q, row in series.items():
        theirs = value_of(row, field)
        mine = ours.get(q)
        if mine is None or theirs is None or q == qe:
            continue
        # an exactly-0.0 stored figure against a real printed magnitude is our own not-reported
        # sentinel, logged and skipped -- never used to veto (feedback-zero-is-a-no-base-sentinel)
        if mine == 0.0 and abs(theirs) > 1.0:
            our_zeros.append("%d ours=0.0 site=%s" % (q, theirs))
            continue
        dist = abs(qidx(q) - ti)
        checked += 1
        a = agree(mine, theirs, unit)
        if a == "no":
            (bad_local if dist <= LOCAL_Q else bad_far).append(
                "%d ours=%s site=%s (%dq away)" % (q, mine, theirs, dist))
            continue
        matched += 1
        worst = max(worst, abs(mine - theirs))
        if dist <= LOCAL_Q:
            local += 1
    nbad = len(bad_local) + len(bad_far)
    near = any(abs(qidx(q) - ti) <= NEAR_Q for q, row in series.items()
               if q != qe and ours.get(q) is not None and value_of(row, field) is not None
               and agree(ours[q], value_of(row, field), unit) != "no")
    why = ""
    if bad_local:
        why = "GATE-A: disagreement inside +-%dq beyond the print unit: %s" % (LOCAL_Q, "; ".join(bad_local[:3]))
    elif local < MIN_ANCHORS:
        why = "GATE-A: only %d anchor(s) inside +-%dq, need %d (%d matched overall)" % (
            local, LOCAL_Q, MIN_ANCHORS, matched)
    elif not near:
        why = "GATE-A2: no reproduced anchor within %dq of %d" % (NEAR_Q, qe)
    elif checked and nbad / float(checked + nbad) > GLOBAL_MAX_BAD:
        why = "GATE-A4: %d/%d of the series disagrees -- different entity/basis" % (nbad, checked + nbad)
    return {"ok": not why, "why": why, "matched": matched, "local": local, "checked": checked,
            "worst": round(worst, 4), "bad_local": bad_local, "bad_far": bad_far,
            "our_zeros": our_zeros, "unit": unit}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    REV = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    cells = json.load(open(a.cells))
    cache, props, reports = {}, {}, {}
    t0 = time.time()

    for i, (sym, qe, field) in enumerate(sorted(cells)):
        qe = int(qe)
        key = "%s|%d|%s" % (sym, qe, field)
        con = field.endswith("C")
        ck = (sym, con)
        if ck not in cache:
            try:
                q = quarters(sym, con=con) or {}
                cache[ck] = {int(dk.replace("-", "")): row for dk, row in q.items()}
            except Exception as e:
                cache[ck] = {}
                reports[key] = {"state": "NOT-FOUND", "why": "screener: %s" % repr(e)[:90]}
        series = cache[ck]
        note = "screener: %d quarters %s..%s" % (
            len(series), min(series, default="-"), max(series, default="-"))
        if qe not in series:
            reports[key] = {"state": "NOT-FOUND", "why": note + "; target quarter absent"}
        else:
            val = value_of(series[qe], field)
            ours = ours_series(REV, sym, field)
            other = ours_series(REV, sym, OTHER[field])
            v = gate(series, ours, qe, field)
            if val is None:
                reports[key] = {"state": "NOT-FOUND", "why": note + "; row missing for this quarter"}
            elif not v["ok"]:
                reports[key] = {"state": "REJECT-GATE", "why": v["why"], "note": note}
            elif abs(val) < MIN_MAGNITUDE:
                # THE WESTLIFE RULE -- see the module docstring
                reports[key] = {"state": "REJECT-MAGNITUDE", "note": note,
                                "why": "value %.2f is under %.0f cr, so screener's +-%.2f cr print "
                                       "rounding is material to it" % (val, MIN_MAGNITUDE, v["unit"])}
            elif val == 0:
                reports[key] = {"state": "REJECT-ZERO-SENTINEL", "note": note,
                                "why": "GATE-B: a printed 0 is the not-reported sentinel"}
            elif other.get(qe) is not None and abs(other[qe] - val) <= v["unit"]:
                reports[key] = {"state": "REJECT-EQUALS-OTHER-BASIS", "note": note,
                                "why": "GATE-C: equals stored %s %.2f (copied-con fingerprint)"
                                       % (OTHER[field], other[qe])}
            else:
                prec = "screener-exact" if v["worst"] <= EXACT_ABS else "screener-rounded(%.2f)" % v["unit"]
                props[key] = {
                    "value": val,
                    "state": "FILLED-EXACT" if v["worst"] <= EXACT_ABS else "FILLED-ROUNDED",
                    "chosen": {"site": "sc", "cand": "Operating Profit" if field.startswith("op")
                               else "Operating Profit - Depreciation",
                               "row": "Operating Profit" if field.startswith("op")
                               else "Operating Profit - Depreciation",
                               "anchors": v["local"], "worst_anchor": v["worst"],
                               "precision": prec},
                    "corroborated_by": [],
                    "sites": {"sc": note},
                }
                reports[key] = {"state": props[key]["state"], "note": note,
                                "anchors": v["local"], "worst": v["worst"]}
        print("[%4d/%4d] %-12s %-8d %-6s %s" % (i + 1, len(cells), sym, qe, field,
                                                reports[key]["state"]))
        sys.stdout.flush()

    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M IST"), "sites": ["sc"],
               "proposals": props, "reports": reports},
              open(a.out, "w"), indent=1, sort_keys=True)
    by = {}
    for r in reports.values():
        by[r["state"]] = by.get(r["state"], 0) + 1
    print("\n%d/%d gated OK -> %s  (%.0fs)" % (len(props), len(cells), a.out, time.time() - t0))
    for k in sorted(by, key=lambda x: -by[x]):
        print("   %-28s %d" % (k, by[k]))


if __name__ == "__main__":
    main()
