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
"""THE GATE. No aggregator number reaches a ledger without passing every check in here.

Shape copied from scripts/fill2020_tools/screener_gate.py (runbook §60c) because that shape has
already caught real corruption (TMPV's demerged entity, SWANCORP's bad stored cell). The core rule
is unchanged and absolute:

    the site's OWN series for that field must reproduce >= MIN_ANCHORS values we already store,
    with ZERO disagreements. One disagreement => different entity, different basis, or a restated
    vintage => REJECT THE WHOLE SERIES. Never cherry-pick the one cell you wanted.

On top of that, six traps this route has that the screener route did not, each its own gate:

 A2  RESTATEMENT / DEMERGER NEIGHBOURHOOD (§60d Gate A2). Aggregators carry restated figures where
     our series is as-reported; subtracting or copying across a restatement boundary yields a
     plausible-looking wrong number. A disagreement anywhere already kills the series, so the
     residual risk is a target sitting far from any anchor -- a stretch where the vintage could
     have changed with nothing to notice it. NEAR_Q requires a reproduced anchor within 4 quarters
     of the target, and REJECTS the target's own quarter if either immediate neighbour disagrees.
 B   THE ZERO SENTINEL. A printed 0 usually means NOT REPORTED, not nil (the guard added to
     screener_fill_all.py on 2026-08-11; memory: feedback-zero-is-a-no-base-sentinel). Held, never
     written, unless our OTHER basis independently shows a genuine ~0 for that quarter.
 C   THE COPIED-CON FINGERPRINT. A value equal to what we already store for the OTHER basis is
     refused (memory: project-stocks-con-copy-defect). If con really equals std the no-sub identity
     route (§6A) is what writes it, with evidence -- not a blind aggregator copy.
 D   ROW CONVENTION IS PROVEN, NOT ASSUMED. Bank revenue is Interest Earned, insurer revenue is the
     premium + investment-income legs, industrial revenue is revenue-from-operations -- and each
     site labels them differently again. So every candidate row is tried and only the row that
     REPRODUCES OUR STORED VALUES is used. If no row reproduces them, the answer is "this site's
     revenue row is a different quantity from ours", i.e. reject -- not "close enough".
 E   CROSS-SITE CORROBORATION. Where more than one site passes, their values for the target must
     agree; a divergence means at least one is wrong and neither is written. (Measured caveat,
     runbook §80c: Moneycontrol and Trendlyne agree to the paisa on identical rows and are NOT
     independent readers, so agreement between those two is weak evidence -- it is recorded, and
     an INDEPENDENT confirmation is a filing read, not a second aggregator.)
 F   PRECISION IS MEASURED, NOT ASSUMED. The anchors tell us how precise this site is FOR THIS
     COMPANY: if every matched anchor lands within 0.01 the site is at filing precision here and
     the fill is `site-exact`; otherwise the worst anchor error is recorded and the fill is
     `rounded` -- the §60e rule that a labelled approximation beats a hole, but must be labelled.

  python3 -X utf8 scripts/agg_tools/agg_gate.py WESTLIFE 20200630 revC
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import agg_sources as A  # noqa: E402

MIN_ANCHORS = 2  # §60c: two reproduced values, zero disagreements
NEAR_Q = 4  # A2: an anchor must exist within this many quarters of the target
# §60d says it in one line: "reject the YEAR, not the company -- and reject years adjacent to a
# restated year too". So the zero-disagreement rule is LOCAL, not global. Measured on the 142-cell
# sweep of 2026-08-11: 45 of the 97 gate refusals were >=90% agreement whose only disagreements sat
# 6-30 quarters away from the target, several of them our own known-bad cells (ADANIENT 2014-12
# stored 2.44 against 17,849.84; KSB 2018-12 stored 0.0 against 346.6). A global veto throws away a
# well-anchored 2022 fill because of a 2014 defect. Local windows, plus a global rate check that
# still kills a whole-entity mismatch (TMPV-style ~40% disagreement).
LOCAL_Q = 6  # anchors must live here, and NOTHING may disagree here
# GUARD_Q was 12 (three years either side) and it was WRONG -- measured 2026-08-11. ACC 2021-12,
# STAR 2021-12 and PFC 2022-06 each have TWELVE local anchors reproduced to the paisa, and each was
# refused for one disagreement 11-12 quarters away. Those distant misses are usually OUR defective
# cells (ADANIENT 2014-12 stored 2.44 vs 17,849.84; KSB 2018-12 stored 0.0), so the veto punished
# the wrong cell. Restatement is A5's job -- the site's own quarters vs its own annual for the
# target FY and both neighbours -- and A5 is what actually caught every real restatement (ICIL,
# PEL, WELCORP, ADANIENT, EXIDEIND, SAMMAANCAP). A3 was redundant with it and cost real reach.
# Distant disagreements are now RECORDED in provenance and reported as suspects, not used to veto.
GUARD_Q = LOCAL_Q  # A3 collapses into A; see A5 in agg_fy_check.py
GLOBAL_MAX_BAD = 0.15  # beyond that it is a different entity/basis, not a restated year
# TOLERANCES ARE SET FROM MEASURED PRINT PRECISION, not inherited. screener.in prints crore-ROUNDED
# integers, so screener_gate.py needs a 1.0-crore absolute floor. Moneycontrol and Trendlyne print
# TWO DECIMALS of a crore (measured 2026-08-11: WESTLIFE Jun-2026 con 735.64 / 742.23 on both), so
# a 1.0 floor here would be ~5x the whole revenue of a holding company and would wave through
# anything: with it, WESTLIFE standalone "agreed" 13/16 while our 0.47/0.30/0.32 sat against the
# site's 0.21/0.22/0.26. Floors below are one print-unit wide, no more.
EXACT_ABS = 0.006  # |diff| at or under this = same number, both printed at 2dp
EXACT_REL = 0.0002
ROUND_ABS = 0.02  # our stored figure is coarser (an older crore-rounded fill) but the same
ROUND_REL = 0.002
CROSS_ABS = 0.02  # gate E: two sites' values for the target must land this close
CROSS_REL = 0.002

FIELD_CANDS = {
    "revS": ("rev_ops", "rev_total"),
    "revC": ("rev_ops", "rev_total"),
    "patS": ("pat_total",),
    "patC": ("pat_own", "pat_total"),
    # Both op/ebit candidates are offered on BOTH bases and Gate D picks the strict winner. Scored
    # over 12 companies x 2 bases on 2026-08-12, `*_pre` won 24 of 24 with zero ties (ATUL 24/0/0
    # std and 22/0/0 con, ZFCVINDIA 18/0/0 both, POWERINDIA 23/0/0, UNOMINDA con 29/0/0), so the
    # preference below is measured, not assumed -- and `*_post` stays a candidate because a tie or
    # a reversal on some company must show up as UNRESOLVED rather than be defined away.
    # op_der (agg_sources.MC_TOPDOWN, 2026-09-05) comes LAST: it exists on every row, so it only
    # decides a cell the printed subtotals could not (pre-2008 rows print `--` for them), and it is
    # scored on the company's own stored quarters like any other candidate.
    "opS": ("op_pre", "op_post", "op_der"),
    "opC": ("op_pre", "op_post", "op_der"),
    "ebitS": ("ebit_pre", "ebit_post"),
    "ebitC": ("ebit_pre", "ebit_post"),
}
OTHER = {
    "revS": "revC",
    "revC": "revS",
    "patS": "patC",
    "patC": "patS",
    "opS": "opC",
    "opC": "opS",
    "ebitS": "ebitC",
    "ebitC": "ebitS",
}
# sf_revop cell layout: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
REVOP_SLOT = {"revS": 0, "revC": 1, "opS": 2, "opC": 3, "ebitS": 7, "ebitC": 8}
_STORE = {}


def ours_series(sym, field):
    """{qe_int: value} -- rev/op/ebit from sf_revop (REVOP_SLOT), patS/patC from sf_fundamentals 1/3."""
    if field in REVOP_SLOT:
        if "revop" not in _STORE:
            _STORE["revop"] = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
        d = _STORE["revop"].get(sym) or {}
        i = REVOP_SLOT[field]
        return {int(q): v[i] for q, v in d.items() if v and len(v) > i and v[i] is not None}
    if "fund" not in _STORE:
        _STORE["fund"] = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    d = _STORE["fund"].get(sym) or []
    i = 1 if field.endswith("S") else 3
    return {r[0]: r[i] for r in d if len(r) > i and r[i] is not None}


def qidx(qe):
    """Quarter ordinal, so 'within 4 quarters' is arithmetic rather than date maths."""
    return (qe // 10000) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[(qe // 100) % 100]


def _agree(mine, theirs):
    d = abs(mine - theirs)
    if d <= max(EXACT_ABS, abs(mine) * EXACT_REL):
        return "exact"
    if d <= max(ROUND_ABS, abs(mine) * ROUND_REL):
        return "rounded"
    return "no"


def check_series(series, ours, cand, qe, field=""):
    """Gate A + A2 for ONE candidate row on ONE site. -> dict verdict.

    Four separate conditions, all required:
      A   >= MIN_ANCHORS reproduced quarters inside +-LOCAL_Q of the target, and NONE disagreeing
      A2  at least one of those anchors within NEAR_Q of the target
      A3  no disagreement anywhere within +-GUARD_Q (a restatement boundary near the target)
      A4  global disagreement rate under GLOBAL_MAX_BAD (a wholly different entity or basis)
    A stored 0.0 revenue is treated as "we hold nothing" rather than as a disagreement: a printed
    zero in a revenue slot is the not-reported sentinel on our side too (memory:
    feedback-zero-is-a-no-base-sentinel), so it is logged as a suspect, never used to veto.
    """
    ti = qidx(qe)
    matched = local = worst = 0
    worst = 0.0
    bad_local, bad_guard, bad_far, our_zeros = [], [], [], []
    checked = 0
    for q, row in series.items():
        theirs = row.get(cand)
        mine = ours.get(q)
        if mine is None or theirs is None or q == qe:
            continue
        dist = abs(qidx(q) - ti)
        # op/ebit share the sentinel: an exactly-0.0 stored figure against a site printing a real
        # magnitude is "we hold nothing here", not a disagreement. Logged as a suspect, never a veto.
        if field in REVOP_SLOT and mine == 0.0 and abs(theirs) > 1.0:
            our_zeros.append("%d ours=0.0 site=%s" % (q, theirs))
            continue
        checked += 1
        if _agree(mine, theirs) == "no":
            txt = "%d ours=%s site=%s (%dq away)" % (q, mine, theirs, dist)
            (bad_local if dist <= LOCAL_Q else bad_guard if dist <= GUARD_Q else bad_far).append(txt)
            continue
        matched += 1
        worst = max(worst, abs(mine - theirs))
        if dist <= LOCAL_Q:
            local += 1
    nbad = len(bad_local) + len(bad_guard) + len(bad_far)
    near = any(
        abs(qidx(q) - ti) <= NEAR_Q
        for q, row in series.items()
        if q != qe and ours.get(q) is not None and row.get(cand) is not None and _agree(ours[q], row[cand]) != "no"
    )
    why = ""
    if bad_local:
        why = "GATE-A: disagreement inside +-%dq: %s" % (LOCAL_Q, "; ".join(bad_local[:3]))
    elif local < MIN_ANCHORS:
        why = "GATE-A: only %d anchor(s) inside +-%dq, need %d (%d matched overall)" % (
            local,
            LOCAL_Q,
            MIN_ANCHORS,
            matched,
        )
    elif not near:
        why = "GATE-A2: no reproduced anchor within %dq of %d" % (NEAR_Q, qe)
    elif bad_guard:
        why = "GATE-A3: restatement boundary inside +-%dq: %s" % (GUARD_Q, "; ".join(bad_guard[:3]))
    elif checked and nbad / float(checked + nbad) > GLOBAL_MAX_BAD:
        why = "GATE-A4: %d/%d of the whole series disagrees -- different entity/basis" % (nbad, checked + nbad)
    return {
        "ok": not why,
        "matched": matched,
        "local": local,
        "checked": checked,
        "bad_local": bad_local,
        "bad_guard": bad_guard,
        "bad_far": bad_far,
        "our_zeros": our_zeros,
        "worst": round(worst, 4),
        "why": why,
        "precision": "site-exact" if worst <= EXACT_ABS else f"rounded({worst:.2f})",
    }


def check(sym, qe, field, sites=("mc", "tl", "tt"), name_hint=""):
    """Full gate for one cell. -> (value or None, verdict dict). Nothing is written here."""
    con = field.endswith("C")
    ours = ours_series(sym, field)
    other = ours_series(sym, OTHER[field])
    out = {"sym": sym, "qe": qe, "field": field, "sites": {}, "value": None, "state": "NOT-FOUND", "notes": []}
    passers = {}
    for site in sites:
        try:
            series, note = A.read(site, sym, con, name_hint)
        except Exception as e:  # transport/parse -> a diagnosis, not absence
            out["sites"][site] = {"note": f"EXC {type(e).__name__}: {e}"}
            continue
        rec = {"note": note}
        if not series:
            out["sites"][site] = rec
            continue
        row = series.get(qe)
        if not row:
            rec["verdict"] = "quarter %d absent (site holds %s..%s)" % (qe, min(series), max(series))
            out["sites"][site] = rec
            continue
        best = None
        for cand in FIELD_CANDS[field]:
            if row.get(cand) is None:
                continue
            v = check_series(series, ours, cand, qe, field)
            v["cand"] = cand
            v["label"] = row.get(cand + "_label")
            v["value"] = row[cand]
            if v["ok"] and (best is None or v["local"] > best["local"]):
                best = v
            elif best is None:
                rec.setdefault("rejected", []).append("{}: {}".format(cand, v["why"]))
        if best:
            rec.update(
                {
                    k: best[k]
                    for k in (
                        "cand",
                        "label",
                        "value",
                        "matched",
                        "local",
                        "checked",
                        "worst",
                        "precision",
                        "bad_far",
                        "our_zeros",
                    )
                }
            )
            rec["verdict"] = "PASS gate A/A2/A3/A4 on %r (%d local + %d total anchors, worst %.2f)" % (
                best["label"],
                best["local"],
                best["matched"],
                best["worst"],
            )
            passers[site] = best
        out["sites"][site] = rec

    if not passers:
        out["state"] = "NOT-FOUND"
        return None, out

    # ---- Gate E: every passing site must agree with every other on the target value
    vals = {s: p["value"] for s, p in passers.items()}
    lo, hi = min(vals.values()), max(vals.values())
    if abs(hi - lo) > max(CROSS_ABS, abs(hi) * CROSS_REL):
        out["state"] = "REJECT-CROSS-SITE"
        out["notes"].append(f"GATE-E: sites disagree on the target: {vals}")
        return None, out

    # prefer the passer with the most LOCAL anchors, tie-broken by the finer precision
    site = min(passers, key=lambda s: (-passers[s]["local"], -passers[s]["matched"], passers[s]["worst"]))
    val = passers[site]["value"]

    # ---- Gate B: a printed zero is 'not reported' until something else says it is a real nil
    if abs(val) < 1e-9:
        peer = other.get(qe)
        if peer is None or abs(peer) > 1.0:
            out["state"] = "REJECT-ZERO-SENTINEL"
            out["notes"].append(f"GATE-B: site prints 0 and nothing corroborates a real nil (other basis = {peer})")
            return None, out
        out["notes"].append(f"GATE-B: zero allowed, other basis also ~0 ({peer})")

    # ---- Gate C: never write our own other-basis value back as this basis
    peer = other.get(qe)
    if peer is not None and _agree(peer, val) != "no":
        out["state"] = "REJECT-EQUALS-OTHER-BASIS"
        out["notes"].append(
            f"GATE-C: {field} {val:.4f} equals stored {OTHER[field]} {peer:.4f} (copied-con fingerprint)"
        )
        return None, out

    out["value"] = val
    out["state"] = "FILLED-EXACT" if passers[site]["precision"] == "site-exact" else "FILLED-ROUNDED"
    out["chosen"] = {
        "site": site,
        "row": passers[site]["label"],
        "cand": passers[site]["cand"],
        "anchors": passers[site]["matched"],
        "local_anchors": passers[site]["local"],
        "checked": passers[site]["checked"],
        "worst_anchor": passers[site]["worst"],
        "precision": passers[site]["precision"],
        "distant_disagreements": passers[site]["bad_far"],
        "our_zero_cells": passers[site]["our_zeros"],
    }
    out["corroborated_by"] = sorted(s for s in passers if s != site)
    return val, out


def main():
    sym, qe, field = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    v, rep = check(sym, qe, field)
    print(json.dumps(rep, indent=1, sort_keys=True))
    print("\n=> {} {}".format(rep["state"], v))


if __name__ == "__main__":
    main()
