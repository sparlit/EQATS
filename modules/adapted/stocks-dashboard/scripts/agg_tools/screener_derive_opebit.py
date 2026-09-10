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
"""ANNUAL DERIVATION for op / ebit -- the lever that reaches 2019-2022.

Both quarterly readers stop short of the gap. Moneycontrol's consolidated tables commonly start
around 2023 and screener's quarterly card holds only the trailing ~13 quarters, while the open
op/ebit cells are concentrated in FY2020-FY2023. screener's ANNUAL P&L holds 10-12 FULL YEARS, and
where we already store the other three quarters of a financial year the fourth falls out by
subtraction (memory: feedback-screener-annual-derivation, runbook §57):

    target quarter = screener annual(FY) - sum(our own other three quarters of that FY)

THE ANCHOR IS THE FY IDENTITY, RUN ON OUR SIDE. Before a single value is derived, screener's annual
series has to reproduce OUR OWN annual sums for the financial years where we hold all four quarters
-- >= MIN_ANCHOR_FYS of them, ZERO disagreements, and at least one of them adjacent to the target FY.
That is what makes a derivation safe rather than arithmetic: if screener is carrying a different
entity, a different basis, or a restated vintage, the identity fails on the neighbouring years and
the whole series is rejected. It is the same rule as §60c/§81e, taken one axis up.

⚠️ RESTATEMENT IS THE REAL RISK HERE, not entity mismatch. An aggregator's annual is the RESTATED
figure while our quarters are as-reported, and subtracting one from the other silently lands the
entire restatement in the derived quarter. Requiring an ADJACENT anchored FY is the guard: a
restatement that moved the target year almost always moves its neighbour too (§60d: "reject the
YEAR, not the company -- and reject years adjacent to a restated one").

⚠️ THE FINANCIAL YEAR IS NOT ALWAYS APR-MAR (§81e). RAIN closes in December, KENNAMET in June. The
FY-end month is read from screener's own annual column dates, never assumed -- assuming March turns
every off-cycle company into a silent NO-TEST, i.e. an untested cell reported as a checked one.

Precision: screener prints crore-ROUNDED integers, so a derived value inherits ~+-0.5 crore from the
annual. Same magnitude guard as screener_opebit.py -- a cell is only written when the print unit is
immaterial to it -- and every fill is labelled `screener-derived-rounded`.

  python3 -X utf8 scripts/agg_tools/screener_derive_opebit.py --elig /tmp/elig.json --out /tmp/d.json
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
from screener_fetch import annuals  # noqa: E402

SLOT = {"opS": 2, "opC": 3, "ebitS": 7, "ebitC": 8}
OTHER = {"opS": "opC", "opC": "opS", "ebitS": "ebitC", "ebitC": "ebitS"}


# A flat crore floor is the wrong shape here and it was measured to be, 2026-08-12. Screener's
# annual is crore-rounded, but on a 1,600 crore figure the residual disagreement against our own
# quarter-sum is a few crore of real accounting difference (ARE&M 0.31%/0.48%, BAYERCROP 0.71%),
# not presentation -- while the genuinely broken series miss by 7% to 2,481% (360ONE, BAJAJFINSV,
# AEGISLOG standalone). So the anchor tolerance is relative, with the crore floor kept underneath it.
def annual_tol(v):
    return max(1.01, abs(v) * 0.005)


MIN_ANCHOR_FYS = 2  # financial years whose identity must reproduce, with zero disagreements
MIN_MAGNITUDE = 50.0  # the WESTLIFE rule (screener_opebit.py) -- rounding must be immaterial
# ★ AND THE ERROR HAS TO BE PROPAGATED, not just tolerated. A 0.5% slack on a 1,600 cr annual is
# 8 cr of slack, which is 2.7% of a 300 cr quarter and 27% of a 30 cr one -- the same absolute
# residue means something completely different depending on what is being derived. So the derived
# cell must be large relative to the WORST anchor error actually observed for this company, which
# bounds its own error at ~2%. Without this the tolerance widening would quietly buy reach by
# writing the least reliable cells.
MIN_ERR_RATIO = 50.0


def value_of(row, field):
    op = row.get("Operating Profit")
    if op is None:
        return None
    if field.startswith("op"):
        return op
    dep = row.get("Depreciation")
    return None if dep is None else round(op - dep, 2)


def fy_end_month(ann_keys):
    """Read the FY-end month off screener's own annual column dates (§81e) -- never assume March."""
    months = Counter(int(k.split("-")[1]) for k in ann_keys)
    return months.most_common(1)[0][0] if months else 3


def fy_of(qe, fem):
    """The financial-year label (its END quarter as YYYYMMDD) that quarter `qe` belongs to."""
    y, m = qe // 10000, (qe // 100) % 100
    end_y = y if m <= fem else y + 1
    dd = {3: 31, 6: 30, 9: 30, 12: 31}[fem]
    return end_y * 10000 + fem * 100 + dd


def quarters_of_fy(fy):
    """The four quarter-ends of the financial year whose LAST quarter is `fy`."""
    out, y, m = [], fy // 10000, (fy // 100) % 100
    for back in (9, 6, 3, 0):
        mm = m - back
        yy = y if mm > 0 else y - 1
        if mm <= 0:
            mm += 12
        out.append(yy * 10000 + mm * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[mm])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elig", required=True, help='{"SYM|S|C": [[qe, field, fy], ...]}')
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    REV = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    elig = json.load(open(a.elig))
    props, reports = {}, {}
    anchor_errs = []
    t0 = time.time()

    for i, (ekey, items) in enumerate(sorted(elig.items())):
        sym, basis = ekey.split("|")
        con = basis == "C"
        try:
            ann = annuals(sym, con=con) or {}
        except Exception as e:
            for qe, field, _ in items:
                reports["%s|%d|%s" % (sym, qe, field)] = {
                    "state": "NOT-FOUND",
                    "why": f"screener annual: {repr(e)[:80]}",
                }
            continue
        annmap = {int(k.replace("-", "")): v for k, v in ann.items()}
        if not annmap:
            for qe, field, _ in items:
                reports["%s|%d|%s" % (sym, qe, field)] = {"state": "NOT-FOUND", "why": "screener: no annual table"}
            continue
        fem = fy_end_month(ann.keys())
        rows = REV.get(sym) or {}

        def cell(q, slot):
            c = rows.get(str(q))
            if not c:
                return None
            c = list(c) + [None] * (9 - len(c))
            return c[slot]

        for qe, field, _ in items:
            key = "%s|%d|%s" % (sym, qe, field)
            slot = SLOT[field]
            fy = fy_of(qe, fem)
            qs = quarters_of_fy(fy)
            if qe not in qs:
                reports[key] = {
                    "state": "NOT-FOUND",
                    "why": "quarter %d is not in FY %d (fy-end month %d)" % (qe, fy, fem),
                }
                continue
            # ---- ANCHOR: screener's annual must reproduce OUR OWN FY sums, zero disagreements
            ok_fys, bad_fys = [], []
            for f in sorted(annmap):
                if f == fy:
                    continue
                fq = quarters_of_fy(f)
                vals = [cell(q, slot) for q in fq]
                if any(v is None for v in vals):
                    continue
                theirs = value_of(annmap[f], field)
                if theirs is None:
                    continue
                mine = round(sum(vals), 2)
                err = abs(mine - theirs)
                (ok_fys if err <= annual_tol(mine) else bad_fys).append((f, mine, theirs, round(err, 2)))
            adjacent = any(abs(f - fy) // 10000 <= 1 for f, _, _, _ in ok_fys)
            tgt_row = annmap.get(fy)
            sibs = [cell(q, slot) for q in qs if q != qe]
            if bad_fys:
                reports[key] = {
                    "state": "REJECT-FY-IDENTITY",
                    "bad": bad_fys[:3],
                    "why": "screener's annual does not reproduce our own FY sum in "
                    "%d year(s) -- different entity/basis/vintage" % len(bad_fys),
                }
            elif len(ok_fys) < MIN_ANCHOR_FYS:
                reports[key] = {
                    "state": "REJECT-NO-ANCHOR",
                    "why": "only %d FY identity anchor(s), need %d" % (len(ok_fys), MIN_ANCHOR_FYS),
                }
            elif not adjacent:
                reports[key] = {
                    "state": "REJECT-NO-ADJACENT-FY",
                    "why": "no anchored FY within one year of %d -- a restatement here would be invisible" % fy,
                }
            elif tgt_row is None or value_of(tgt_row, field) is None:
                reports[key] = {"state": "NOT-FOUND", "why": "screener has no annual row for FY %d" % fy}
            elif any(v is None for v in sibs):
                reports[key] = {"state": "NOT-FOUND", "why": "we no longer hold all three siblings"}
            else:
                derived = round(value_of(tgt_row, field) - sum(sibs), 2)
                other = cell(qe, SLOT[OTHER[field]])
                worst = max(e for _, _, _, e in ok_fys)
                if abs(derived) < MIN_MAGNITUDE:
                    reports[key] = {
                        "state": "REJECT-MAGNITUDE",
                        "why": f"derived {derived:.2f} is under {MIN_MAGNITUDE:.0f} cr, so screener's crore "
                        "rounding is material to it",
                    }
                elif abs(derived) < MIN_ERR_RATIO * max(worst, 0.01):
                    reports[key] = {
                        "state": "REJECT-ERROR-RATIO",
                        "why": f"derived {derived:.2f} is only {abs(derived) / max(worst, 0.01):.0f}x this company's worst FY "
                        f"anchor error ({worst:.2f} cr); need {MIN_ERR_RATIO:.0f}x to bound the cell "
                        "at ~2%",
                    }
                elif other is not None and abs(other - derived) <= annual_tol(derived):
                    reports[key] = {
                        "state": "REJECT-EQUALS-OTHER-BASIS",
                        "why": f"GATE-C: equals stored {OTHER[field]} {other:.2f}",
                    }
                else:
                    anchor_errs.extend(e for _, _, _, e in ok_fys)
                    props[key] = {
                        "value": derived,
                        "state": "FILLED-ROUNDED",
                        "chosen": {
                            "site": "sc",
                            "cand": "annual(FY%d) - our other 3 quarters" % fy,
                            "row": "Operating Profit%s (annual)"
                            % ("" if field.startswith("op") else " - Depreciation"),
                            "anchors": len(ok_fys),
                            "worst_anchor": worst,
                            "precision": f"screener-derived-rounded(worst FY anchor {worst:.2f} cr)",
                        },
                        "corroborated_by": [],
                        "sites": {
                            "sc": "screener annual %d FYs, %d identity anchors, fy-end month %d"
                            % (len(annmap), len(ok_fys), fem)
                        },
                    }
                    reports[key] = {"state": "FILLED-ROUNDED", "fy": fy, "anchors": len(ok_fys), "worst": worst}
            print("[%3d/%3d] %-12s %-8d %-6s %s" % (i + 1, len(elig), sym, qe, field, reports[key]["state"]))
            sys.stdout.flush()

    json.dump(
        {"generated": time.strftime("%Y-%m-%d %H:%M IST"), "sites": ["sc"], "proposals": props, "reports": reports},
        open(a.out, "w"),
        indent=1,
        sort_keys=True,
    )
    by = Counter(r["state"] for r in reports.values())
    print("\n%d/%d derived -> %s  (%.0fs)" % (len(props), len(reports), a.out, time.time() - t0))
    for k, n in by.most_common():
        print("   %-28s %d" % (k, n))
    if anchor_errs:
        anchor_errs.sort()
        print(
            f"   FY-identity anchor error: median {anchor_errs[len(anchor_errs) // 2]:.2f}  p90 {anchor_errs[int(len(anchor_errs) * 0.9)]:.2f}  max {anchor_errs[-1]:.2f} (cr)"
        )


if __name__ == "__main__":
    main()
