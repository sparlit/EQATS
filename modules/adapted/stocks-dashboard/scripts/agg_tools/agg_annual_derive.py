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
"""THE ANNUAL LEVER — the missing 4th quarter of an FY = the site's annual minus our 3 stored ones.

Runbook §60d, applied to the aggregator route. It exists because the first sweep only ever read the
sites' QUARTERLY tables, and those bottom out at 13 quarters on Trendlyne / 10 on Tickertape — while
their ANNUAL tables reach FY2016 (TL/TT) and FY1990-98 (Moneycontrol). Measured on the 129 cells the
quarterly sweep left open: 47 of them have all three FY siblings already stored, i.e. exactly the
shape this route serves.

★ THE TRAP THIS ROUTE IS FAMOUS FOR (§60d Gate A2): the site's annual is often RESTATED while our
quarters are as-reported. Subtracting one from the other yields a residual that passes every
plausibility check and is simply wrong. So the gates below are not optional garnish; they are the
route.

  A   ENTITY/BASIS/VINTAGE. For every FY where we hold all four quarters, our sum must reproduce the
      site's annual. Require >= MIN_FY agreeing years and ZERO disagreeing ones inside the guard
      window around the target FY. A disagreement is a restated year, not noise.
  A2  ADJACENCY. The FY before and after the target must also pass A, where testable. §60d: reject
      years adjacent to a restated year too.
  A5  SITE-INTERNAL. Where the site holds all four quarters of the target FY, its own quarters must
      sum to its own annual (agg_fy_check.site_fy_identity).
  S   SIBLING IDENTITY — the one specific to THIS route. Where the site prints the sibling quarters
      we are subtracting, OUR stored value and ITS value must agree. Otherwise the arithmetic mixes
      two vintages: our as-reported siblings against their restated annual. That mixture is the
      §60d garbage residual, and it is invisible afterwards.
  X   CROSS-CHECK. Where the site also prints the target quarter, the derived value must reproduce
      it. (When it does, the derivation adds no new number -- but it is a second, independent
      arithmetic confirmation of one, so it is recorded and welcome.)
  B   RESIDUAL SANITY. Derived value > 0 and within 0.2x-5x the median stored sibling. Catches the
      case where one of the three STORED quarters is itself wrong (§60d's AIIL example).

  python3 -X utf8 scripts/agg_tools/agg_annual_derive.py --cells open.json --out derived.json
"""
import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_fy_check as F  # noqa: E402
import agg_gate as G  # noqa: E402
import agg_sources as A  # noqa: E402

MIN_FY = 3  # §60d: at least three FYs where our 4 quarters reproduce their annual
GUARD_FY = 2  # ... and no disagreeing FY within this many years of the target
SIB_TOL_ABS = 0.02
SIB_TOL_REL = 0.002
BAND_LO, BAND_HI = 0.2, 5.0


def _close(a, b, ta=SIB_TOL_ABS, tr=SIB_TOL_REL):
    return abs(a - b) <= max(ta, abs(b) * tr)


def derive(sym, qe, field, sites=("mc", "tl", "tt")):
    con = field.endswith("C")
    ours = G.ours_series(sym, field)
    out = {"sym": sym, "qe": qe, "field": field, "sites": {}, "value": None, "state": "NOT-FOUND"}

    for site in sites:
        rec = {}
        try:
            ann, anote = A.read_annual(site, sym, con)
            q, _qnote = A.read(site, sym, con)
        except Exception as e:
            out["sites"][site] = {"note": f"EXC {type(e).__name__}: {e}"}
            continue
        rec["note"] = anote
        if not ann:
            out["sites"][site] = rec
            continue
        fem = F.fy_end_month(ann)
        qs, fy = F.fy_quarters(qe, fem)
        sibs = [x for x in qs if x != qe]
        if any(ours.get(x) is None for x in sibs):
            rec["verdict"] = "we do not hold all 3 siblings for FY%d" % fy
            out["sites"][site] = rec
            continue

        for cand in G.FIELD_CANDS[field]:
            target = (ann.get(fy) or {}).get(cand)
            if target is None:
                continue
            # ---- Gate A / A2 : our-4-quarter FYs vs the site's annual, same row
            agree, bad, near_bad = 0, [], []
            for f2, row in ann.items():
                t2 = row.get(cand)
                # An annual table can carry a NON-quarter year end: SPICEJET's Moneycontrol annual
                # holds "May '94" (a 14-month transition year). Those rows have no four quarter-ends
                # to sum, and feeding one to fy_quarters raises. Skip, do not crash.
                if t2 is None or f2 == fy or (f2 // 100) % 100 not in F._LASTDAY:
                    continue
                q4, _ = F.fy_quarters(f2, fem)
                if any(ours.get(x) is None for x in q4):
                    continue
                s2 = sum(ours[x] for x in q4)
                if _close(s2, t2, 0.5, 0.004):
                    agree += 1
                else:
                    txt = "FY%d ours=%.2f site=%.2f" % (f2, s2, t2)
                    bad.append(txt)
                    if abs(f2 // 10000 - fy // 10000) <= GUARD_FY:
                        near_bad.append(txt)
            if agree < MIN_FY:
                rec.setdefault("rejected", []).append(
                    "%s: GATE-A only %d testable FY(s) agree, need %d" % (cand, agree, MIN_FY)
                )
                continue
            if near_bad:
                rec.setdefault("rejected", []).append(
                    "%s: GATE-A2 restated FY within %dy of target: %s" % (cand, GUARD_FY, "; ".join(near_bad[:2]))
                )
                continue
            # ---- Gate A5 : the site's own quarters vs its own annual, target FY + neighbours
            a5 = {
                t: F.site_fy_identity(site, sym, con, cand, f2, fem)[0]
                for t, f2 in (("target", fy), ("prev", fy - 10000), ("next", fy + 10000))
            }
            if "RESTATED" in a5.values():
                rec.setdefault("rejected", []).append(f"{cand}: GATE-A5 site's own FY identity fails ({a5})")
                continue
            # ---- Gate S : the siblings we subtract must be the SAME vintage as their annual
            sib_bad = [
                "%d ours=%.2f site=%.2f" % (x, ours[x], (q.get(x) or {})[cand])
                for x in sibs
                if (q.get(x) or {}).get(cand) is not None and not _close(ours[x], (q.get(x) or {})[cand])
            ]
            if sib_bad:
                rec.setdefault("rejected", []).append(
                    "{}: GATE-S sibling vintage mismatch: {}".format(cand, "; ".join(sib_bad))
                )
                continue
            val = round(target - sum(ours[x] for x in sibs), 2)
            # ---- Gate B : residual sanity
            med = statistics.median([ours[x] for x in sibs])
            if val <= 0 or not (BAND_LO * abs(med) <= abs(val) <= BAND_HI * abs(med)):
                rec.setdefault("rejected", []).append(
                    f"{cand}: GATE-B residual {val:.2f} outside {BAND_LO:.1f}x-{BAND_HI:.1f}x median sibling {med:.2f}"
                )
                continue
            # ---- Gate X : if the site also prints the quarter, the derivation must reproduce it
            printed = (q.get(qe) or {}).get(cand)
            xchk = None
            if printed is not None:
                if not _close(val, printed, 0.5, 0.004):
                    rec.setdefault("rejected", []).append(
                        f"{cand}: GATE-X derived {val:.2f} != site's own printed {printed:.2f}"
                    )
                    continue
                xchk = printed
            rec.update(
                {
                    "cand": cand,
                    "value": val,
                    "fy": fy,
                    "fy_end_month": fem,
                    "site_annual": target,
                    "our_siblings": {str(x): ours[x] for x in sibs},
                    "agreeing_FYs": agree,
                    "distant_restated_FYs": bad,
                    "site_prints_quarter": xchk,
                    "a5": a5,
                    "verdict": "PASS (annual FY%d %.2f - our 3 siblings; %d FYs reproduce)" % (fy, target, agree),
                }
            )
            break
        out["sites"][site] = rec

    passers = {s: v for s, v in out["sites"].items() if v.get("value") is not None}
    if not passers:
        return None, out
    vals = {s: v["value"] for s, v in passers.items()}
    if max(vals.values()) - min(vals.values()) > max(0.5, abs(max(vals.values())) * 0.004):
        out["state"] = "REJECT-CROSS-SITE"
        out["notes"] = [f"sites disagree on the derived value: {vals}"]
        return None, out
    site = min(passers, key=lambda s: -passers[s]["agreeing_FYs"])
    val = passers[site]["value"]

    other = G.ours_series(sym, G.OTHER[field]).get(qe)
    if other is not None and _close(val, other):
        out["state"] = "REJECT-EQUALS-OTHER-BASIS"
        out["notes"] = [f"derived {val:.2f} equals stored {G.OTHER[field]} {other:.2f}"]
        return None, out
    if abs(val) < 1e-9:
        out["state"] = "REJECT-ZERO-SENTINEL"
        return None, out

    out["value"] = val
    out["state"] = "FILLED-DERIVED"
    out["chosen"] = dict(passers[site], site=site)
    out["corroborated_by"] = sorted(s for s in passers if s != site)
    return val, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--skip-filled", default=os.path.join(os.path.dirname(HERE), "agg_cell_fills.json"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cells = json.load(open(a.cells))
    done = set(json.load(open(a.skip_filled))) if os.path.exists(a.skip_filled) else set()
    props, reports = {}, {}
    for _i, (sym, qe, field) in enumerate(sorted(cells)):
        if f"{sym}|{qe}" in done:
            continue
        key = f"{sym}|{qe}|{field}"
        v, rep = derive(sym, int(qe), field)
        reports[key] = rep
        if v is not None:
            props[key] = {
                "value": v,
                "state": rep["state"],
                "chosen": rep["chosen"],
                "corroborated_by": rep["corroborated_by"],
            }
        why = rep.get("chosen", {}).get("verdict") or "; ".join(
            r
            for v in rep["sites"].values()
            for r in v.get("rejected", []) or ([v["verdict"]] if v.get("verdict") else [])
        )
        print("%-26s %-16s %s" % (key, rep["state"], why[:135]))
        sys.stdout.flush()
    json.dump({"proposals": props, "reports": reports}, open(a.out, "w"), indent=1, sort_keys=True)
    print("\nderived %d -> %s" % (len(props), a.out))


if __name__ == "__main__":
    main()
