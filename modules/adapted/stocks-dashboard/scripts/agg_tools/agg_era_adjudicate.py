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
"""GATE E, second pass: adjudicate the near-target DISAGREEMENT before letting it veto.

1,010 of GATE E's 1,613 refusals were "the site disagrees with one of OUR stored cells within +-6
quarters of the target". That rule is right to exist and wrong to apply blind, because a
disagreement names two cells and indicts neither. Runbook §81e measured the same thing from the
other side: 45 of 97 refusals on the 2026 sweep were >=90%-agreeing series whose only disagreements
were OUR known-bad cells (ADANIENT 2014-12 stored 2.44 against 17,849.84; KSB 2018-12 stored 2.53
against 25.30).

So each disagreeing quarter is put to the §45 FY quarter-sum identity, which is proof rather than
inference -- an audited annual is not free to disagree with its own four quarters:

    site's 4 quarters == site's annual   AND   swap OUR value in and it no longer closes
        -> OURS-IS-THE-OUTLIER. The site's series is internally coherent at that FY and our cell
           is what breaks it. The disagreement indicts us, so it does not veto the target.
    site's 4 quarters != its own annual  -> SITE-INCOHERENT: the veto stands (and the whole FY is
           already refused by E2).
    identity untestable (a quarter or the annual missing) -> UNDECIDED: the veto stands.

⚠️ What this does NOT do: touch the indicted cell. §58d -- correcting a stored value is its own
procedure with its own evidence, never a side effect of a fill pass. Every OURS-IS-THE-OUTLIER
verdict is written to a SUSPECTS file for separate adjudication, and nothing in our data changes.
Memory: feedback-identity-fails-doesnt-name-the-cell, feedback-heal-the-row-not-the-cell.

Everything else about GATE E is unchanged -- the excused quarters are removed from the anchor pool
too, so an excused cell can never be counted as agreement.

  python3 -X utf8 scripts/agg_tools/agg_era_adjudicate.py --cells /tmp/open_cells_0214.json \
          --reach /tmp/reach_0214.json --out /tmp/era2_props.json --suspects /tmp/era2_suspects.json
"""
import argparse
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import agg_era_gate as EG  # noqa: E402
import agg_gate as G  # noqa: E402
import mc_era as E  # noqa: E402

MAX_EXCUSED = 2  # per symbol -- see excusal_allowed()
MAX_EXCUSED_RATE = 0.02


def annual_is_independent(series, ann, cand):
    """Does this company's annual row carry information its quarterly row does not?

    ⚠️ THE TEST THAT KEEPS THE WHOLE PASS HONEST. "The site's four quarters sum to the site's own
    annual" is worthless if the site COMPUTED that annual from those quarters -- it would close for
    a corrupt series just as happily. GLAXO 2011 is the worked example: MC prints 0.46 for Mar-2011
    between quarters of 115.70 and 147.54 (we store 186.33), and its CY2011 annual is 430.60 =
    0.46+147.54+145.86+136.74 exactly, i.e. the annual inherited the bad quarter.

    So: over the company's own history, is there at least one FY where the annual DIFFERS from the
    sum of its four quarters? If yes the annual is a separately-sourced row and its agreement at
    the target FY is evidence. If it matches everywhere, this company's annual is (or behaves
    exactly like) a derived total and cannot arbitrate anything.
    """
    tested = diverged = 0
    for fyend in sorted(ann):
        if (fyend // 100) % 100 not in EG._LASTDAY:
            continue  # off-frame FY end (some tables carry a Jul/Oct stub) -- not testable
        qs = [EG.qde(EG.qord(fyend) - k) for k in (3, 2, 1, 0)]
        vals = [(series.get(x) or {}).get(cand) for x in qs]
        target = (ann.get(fyend) or {}).get(cand)
        if target is None or any(v is None for v in vals):
            continue
        tested += 1
        if not EG._close(sum(vals), target):
            diverged += 1
    return (diverged > 0), {"fys_tested": tested, "fys_where_annual_differs": diverged}


def adjudicate_symbol(sym, ident, field="patS", hi=20141231):
    """-> ({qe: verdict}, [suspect records], meta). One FY-identity test per disagreeing quarter."""
    con = field.endswith("C")
    series, _ = E.quarters(ident, con)
    ann, _ = EG._era_annual(ident, con)
    ours = G.ours_series(sym, field)
    cand = G.FIELD_CANDS[field][0]
    verdicts, suspects = {}, []
    for qe in sorted(series):
        if qe not in ours or (qe // 100) % 100 not in EG._LASTDAY:
            continue
        v = series[qe].get(cand)
        if v is None or G._agree(ours[qe], v) != "no":
            continue
        fem, femwhy = EG.fy_end_month_near(ann, qe)
        _, fyend = EG.fy_of(qe, fem)
        state, det = EG.site_fy(series, ann, cand, fyend)
        if state != "OK":
            verdicts[qe] = "SITE-INCOHERENT" if state == "RESTATED" else "UNDECIDED"
            continue
        # the site's FY closes. Does it still close with OUR value swapped in?
        qs = [EG.qde(EG.qord(fyend) - k) for k in (3, 2, 1, 0)]
        swapped = sum(ours[qe] if x == qe else series[x][cand] for x in qs)
        annv = ann[fyend][cand]
        if EG._close(swapped, annv):
            verdicts[qe] = "UNDECIDED"  # both fit -> the identity cannot separate them
            continue
        verdicts[qe] = "OURS-IS-THE-OUTLIER"
        if qe <= hi:
            suspects.append(
                {
                    "sym": sym,
                    "qe": qe,
                    "field": field,
                    "ours": ours[qe],
                    "site": v,
                    "site_row": series[qe].get(cand + "_label"),
                    "fy_end": fyend,
                    "fy_end_month_src": femwhy,
                    "site_sum4Q": det["sum4Q"],
                    "site_annual": det["annual"],
                    "sum_with_our_value": round(swapped, 2),
                    "verdict": "the site's own FY closes to the paisa and ours does not; "
                    "reported under §58d, NOT patched here",
                }
            )

    overlap = sum(1 for q in series if q in ours and series[q].get(cand) is not None)
    n_out = sum(1 for v in verdicts.values() if v == "OURS-IS-THE-OUTLIER")
    indep, idet = annual_is_independent(series, ann, cand)
    meta = {"overlap": overlap, "ours_is_outlier": n_out, "annual_independent": indep, "annual_detail": idet}
    # EXCUSAL MUST STAY RARE. Each excusal says "our cell is the broken one"; a series that needs
    # many of them is not a series meeting many of our defects, it is a series that DIFFERS from
    # ours -- and excusing them all would launder a systematically divergent table straight through
    # gate E1, which counts disagreements. NOVARTIND wanted 12 excusals, HUHTAMAKI 5.
    if not indep:
        meta["excusal"] = "REFUSED: this company's annual never differs from its own quarters"
    # OR, not AND: an absolute cap of 2 combined with a 2% rate is unreachable for any overlap
    # under 100 quarters, so AMBUJACEM's 2-in-90 was refused by a rule that could never have
    # admitted it. A symbol qualifies on EITHER a small absolute count OR a small rate.
    elif n_out > MAX_EXCUSED and (not overlap or n_out / float(overlap) > MAX_EXCUSED_RATE):
        meta["excusal"] = "REFUSED: %d excusals over %d overlapping quarters exceeds the cap (%d, %.0f%%)" % (
            n_out,
            overlap,
            MAX_EXCUSED,
            MAX_EXCUSED_RATE * 100,
        )
    else:
        meta["excusal"] = "ALLOWED"
    return verdicts, suspects, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--reach", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--suspects", required=True)
    ap.add_argument("--syms")
    ap.add_argument(
        "--e2b",
        action="store_true",
        help="pass GATE E's E2b setting through to the re-checks this pass runs "
        "(target FY only; see agg_era_gate.NEIGHBOUR_FY_REQUIRED). Without it a "
        "run started under E2b would silently re-check under strict E2.",
    )
    a = ap.parse_args()

    if a.e2b:
        EG.NEIGHBOUR_FY_REQUIRED = False
    cells = [tuple(c) for c in json.load(open(a.cells))]
    if a.syms:
        want = set(a.syms.split(","))
        cells = [c for c in cells if c[0] in want]
    reach = json.load(open(a.reach))
    idcache = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}

    by_sym = collections.defaultdict(list)
    for sym, qe, field in cells:
        by_sym[sym].append((int(qe), field))

    props, reports, suspects, adj_all = {}, {}, [], {}
    t0 = time.time()
    for i, sym in enumerate(sorted(by_sym)):
        ident = idcache.get(sym)
        if not ident or not (reach.get(sym) or {}).get("resolved"):
            continue
        adj, susp, meta = adjudicate_symbol(sym, ident)
        for s in susp:
            s["excusal_for_symbol"] = meta["excusal"]
        suspects.extend(susp)
        adj_all[sym] = dict({str(k): v for k, v in adj.items()}, _meta=meta)
        if meta["excusal"] != "ALLOWED":
            continue
        excused = {q for q, v in adj.items() if v == "OURS-IS-THE-OUTLIER"}
        if not excused:
            continue  # nothing new to try for this symbol
        for qe, field in by_sym[sym]:
            val, rep = EG.check(sym, qe, field, ident=ident, excused=excused)
            key = "%s|%d|%s" % (sym, qe, field)
            reports[key] = rep
            if val is not None:
                props[key] = {
                    "value": val,
                    "state": rep["state"],
                    "chosen": rep["chosen"],
                    "corroborated_by": [],
                    "resolved_via": rep.get("resolved_via"),
                    "fy_check": rep["detail"].get("A5"),
                    "our_fy_identity": rep["detail"].get("our_fy_identity"),
                    "excused_disagreements": rep["detail"].get("excused"),
                    "sites": {"mc": rep.get("site_note")},
                }
        if (i + 1) % 50 == 0:
            print(
                "[%3d/%3d] %-11s (%.0fs) new fills=%d suspects=%d"
                % (i + 1, len(by_sym), sym, time.time() - t0, len(props), len(suspects))
            )
            sys.stdout.flush()

    json.dump(
        {
            "generated": time.strftime("%Y-%m-%d %H:%M IST"),
            "gate": "E + disagreement adjudication",
            "proposals": props,
            "reports": reports,
            "adjudications": adj_all,
        },
        open(a.out, "w"),
        indent=1,
        sort_keys=True,
    )
    json.dump(
        {
            "generated": time.strftime("%Y-%m-%d %H:%M IST"),
            "rule": "site FY identity closes, ours does not -> our cell is the outlier. "
            "REPORTED ONLY, never patched (§58d).",
            "cells": suspects,
        },
        open(a.suspects, "w"),
        indent=1,
        sort_keys=True,
    )
    vc = collections.Counter(v for d in adj_all.values() for k, v in d.items() if k != "_meta")
    print(f"\nadjudicated disagreements: {dict(vc)}")
    print("%d new cells pass GATE E once the indicted-our-cell vetoes are lifted -> %s" % (len(props), a.out))
    print("%d suspect cells of ours reported -> %s" % (len(suspects), a.suspects))


if __name__ == "__main__":
    main()
